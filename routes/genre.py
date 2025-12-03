import json
import math
from typing import Any, Dict, List, Optional, Set

from flask import Blueprint, current_app, jsonify, request

from services.omdb import (
    GENRE_CURATED_IDS,
    expand_search_terms,
    fetch_movie_details,
    omdb_search_request,
    parse_box_office_value,
    parse_int_param,
)
from utils.cache import fetch_from_cache, store_in_cache

GENRE_PAGE_SIZE = 10
GENRE_MAX_PAGES = 10
GENRE_RESULT_LIMIT = GENRE_PAGE_SIZE * GENRE_MAX_PAGES
DEFAULT_HIGH_RATING = 7.0


def _load_json_list(blob: Optional[str]) -> List[Dict[str, Any]]:
    if not blob:
        return []
    try:
        data = json.loads(blob)
        if isinstance(data, list):
            return data
    except Exception:
        current_app.logger.warning("Invalid cached payload ignored")
    return []


def _safe_float(value: Any) -> float:
    if value in (None, "", "N/A"):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_year(value: Any) -> int:
    if not value:
        return 0
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return 0


def _prepare_entry(
    detail: Dict[str, Any],
    curated_lookup: Dict[str, int],
) -> Optional[Dict[str, Any]]:
    imdb_id = detail.get("imdbID")
    if not imdb_id:
        return None

    lower_id = imdb_id.lower()
    rating_value = _safe_float(detail.get("imdbRating"))
    box_office_value = parse_box_office_value(detail.get("BoxOffice"))
    year_value = _safe_year(detail.get("Year"))

    return {
        "title": detail.get("Title"),
        "imdbID": imdb_id,
        "year": detail.get("Year"),
        "poster": detail.get("Poster"),
        "genres": detail.get("Genre"),
        "imdbRating": detail.get("imdbRating"),
        "average_rating": rating_value if rating_value > 0 else None,
        "language": detail.get("Language"),
        "boxOffice": detail.get("BoxOffice"),
        "_rating_val": rating_value,
        "_box_office_val": box_office_value,
        "_year_val": year_value,
        "_curated": lower_id in curated_lookup,
        "_curated_index": curated_lookup.get(lower_id, len(curated_lookup) + 1000),
    }


def _normalise_entries(entries: List[Dict[str, Any]], curated_lookup: Dict[str, int]) -> List[Dict[str, Any]]:
    normalised: List[Dict[str, Any]] = []
    for entry in entries:
        imdb_id = entry.get("imdbID")
        if not imdb_id:
            continue
        lower_id = imdb_id.lower()
        entry["_curated"] = bool(entry.get("_curated")) or lower_id in curated_lookup
        entry["_curated_index"] = entry.get("_curated_index", curated_lookup.get(lower_id, len(curated_lookup) + 1000))
        entry["_rating_val"] = entry.get("_rating_val", _safe_float(entry.get("average_rating") or entry.get("imdbRating")))
        entry["_box_office_val"] = entry.get("_box_office_val", parse_box_office_value(entry.get("boxOffice") or entry.get("BoxOffice")))
        entry["_year_val"] = entry.get("_year_val", _safe_year(entry.get("year") or entry.get("Year")))
        normalised.append(entry)
    return normalised


def _entry_matches_filters(
    entry: Dict[str, Any],
    year_filter: Optional[str],
    language_filter: Optional[str],
    rating_threshold_value: Optional[float],
) -> bool:
    if year_filter and not str(entry.get("year") or "").startswith(str(year_filter)):
        return False
    if language_filter and language_filter.lower() not in (entry.get("language") or "").lower():
        return False
    if rating_threshold_value is not None and entry.get("_rating_val", 0.0) < rating_threshold_value:
        return False
    return True


def _sort_entries(entries: List[Dict[str, Any]], sort_mode: str) -> List[Dict[str, Any]]:
    def sort_key(entry: Dict[str, Any]):
        title_key = (entry.get("title") or "").lower()
        if sort_mode == "rating_asc":
            return (entry.get("_rating_val", 0.0), entry.get("_year_val", 0), title_key)
        if sort_mode == "rating_desc":
            return (entry.get("_rating_val", 0.0), entry.get("_year_val", 0), title_key)
        if sort_mode == "year_asc":
            return (entry.get("_year_val", 0), entry.get("_rating_val", 0.0), title_key)
        if sort_mode == "year_desc":
            return (entry.get("_year_val", 0), entry.get("_rating_val", 0.0), title_key)
        if sort_mode == "title_asc":
            return title_key
        if sort_mode == "title_desc":
            return title_key
        return (entry.get("_rating_val", 0.0), entry.get("_year_val", 0), title_key)

    reverse = sort_mode in {"rating_desc", "year_desc", "title_desc"}
    return sorted(entries, key=sort_key, reverse=reverse)


def _clean_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def _fetch_random_high_rated_entries(
    cache_client,
    omdb_api_key: str,
    genre_name: str,
    needed: int,
    seen_ids: Set[str],
    year_filter: Optional[str],
    language_filter: Optional[str],
    rating_threshold_value: Optional[float],
    curated_lookup: Dict[str, int],
) -> List[Dict[str, Any]]:
    if needed <= 0:
        return []

    lower_genre_name = genre_name.lower()
    base_variants = expand_search_terms(genre_name) or [genre_name]
    extended_variants = list(base_variants)
    extended_variants.extend(
        [
            f"{genre_name} movie",
            f"{genre_name} film",
            f"{genre_name} blockbuster",
            f"{genre_name} cinema",
            f"best {genre_name} movies",
        ]
    )
    seen_terms: Set[str] = set()
    results: List[Dict[str, Any]] = []

    min_rating = rating_threshold_value if rating_threshold_value is not None else DEFAULT_HIGH_RATING

    for term in extended_variants:
        normalized = term.strip().lower()
        if not normalized or normalized in seen_terms:
            continue
        seen_terms.add(normalized)

        for source_page in range(1, 6):
            payload = omdb_search_request(omdb_api_key, term, source_page, current_app.logger)
            if not payload or payload.get("Response") != "True":
                break

            for entry in payload.get("Search", []):
                identifier = entry.get("imdbID")
                if not identifier:
                    continue
                key = identifier.lower()
                if key in seen_ids:
                    continue

                detail, _, _ = fetch_movie_details(cache_client, omdb_api_key, identifier)
                if not detail:
                    continue
                genre_field = (detail.get("Genre") or "").lower()
                if lower_genre_name not in genre_field:
                    continue

                movie_entry = _prepare_entry(detail, curated_lookup)
                if not movie_entry:
                    continue
                if movie_entry.get("_rating_val", 0.0) < min_rating:
                    continue
                if not _entry_matches_filters(movie_entry, year_filter, language_filter, rating_threshold_value):
                    continue

                seen_ids.add(key)
                results.append(movie_entry)
                if len(results) >= needed:
                    return results

            if len(results) >= needed:
                break

    return results


def create_genre_blueprint(cache_client, omdb_api_key: str) -> Blueprint:
    bp = Blueprint("genre", __name__, url_prefix="/api")

    @bp.route("/genres")
    def genres_for_movie() -> Any:
        identifier = (
            request.args.get("title") or request.args.get("imdbID") or request.args.get("id")
        )
        if not identifier:
            return (
                jsonify({"error": "Provide ?title=<movie_title> or ?imdbID=<id> to fetch genres."}),
                400,
            )

        detail, cached_detail, _ = fetch_movie_details(cache_client, omdb_api_key, identifier.strip())
        if not detail:
            return jsonify({"error": "Movie not found."}), 404

        genres = [genre.strip() for genre in detail.get("Genre", "").split(",") if genre.strip()]
        payload = {
            "movie": {
                "title": detail.get("Title"),
                "imdbID": detail.get("imdbID"),
                "year": detail.get("Year"),
                "poster": detail.get("Poster"),
            },
            "genres": genres,
            "cached": cached_detail,
        }
        return jsonify(payload)

    @bp.route("/genre/<genre_name>")
    def browse_genre(genre_name: str) -> Any:
        page = parse_int_param(request.args.get("page"), 1, minimum=1, maximum=GENRE_MAX_PAGES)
        year_filter = request.args.get("year")
        language_filter = request.args.get("language")
        rating_threshold = request.args.get("rating")
        sort_mode = request.args.get("sort") or "rating_desc"
        allowed_sorts = {
            "rating_desc",
            "rating_asc",
            "year_desc",
            "year_asc",
            "title_asc",
            "title_desc",
        }
        if sort_mode not in allowed_sorts:
            sort_mode = "rating_desc"

        try:
            rating_threshold_value = float(rating_threshold) if rating_threshold else None
        except ValueError:
            return jsonify({"error": "rating must be numeric"}), 400

        cache_key = (
            f"genre:browse:{genre_name.lower()}:{page}:{year_filter}:{language_filter}:"
            f"{rating_threshold_value}:{sort_mode}"
        )
        cached_payload = fetch_from_cache(cache_client, cache_key)
        if cached_payload is not None:
            try:
                data = json.loads(cached_payload)
                data["cached"] = True
                return jsonify(data)
            except Exception:
                current_app.logger.warning("Invalid cached genre payload for %s", genre_name)

        lower_genre_name = genre_name.lower()
        curated_ids = GENRE_CURATED_IDS.get(lower_genre_name, [])
        curated_lookup = {imdb_id.lower(): idx for idx, imdb_id in enumerate(curated_ids)}

        curated_entries: List[Dict[str, Any]] = []
        if curated_ids:
            dataset_cache_key = f"genre:dataset:{lower_genre_name}"
            cached_dataset = fetch_from_cache(cache_client, dataset_cache_key)
            curated_entries = _normalise_entries(_load_json_list(cached_dataset), curated_lookup)

            if not curated_entries:
                detailed_entries: List[Dict[str, Any]] = []
                for imdb_id in curated_ids:
                    identifier = imdb_id.strip()
                    if not identifier:
                        continue
                    detail, _, _ = fetch_movie_details(cache_client, omdb_api_key, identifier)
                    if not detail:
                        continue
                    genre_field = detail.get("Genre", "") or ""
                    if lower_genre_name not in genre_field.lower():
                        continue
                    movie_entry = _prepare_entry(detail, curated_lookup)
                    if movie_entry:
                        detailed_entries.append(movie_entry)

                curated_entries = detailed_entries
                store_in_cache(cache_client, dataset_cache_key, curated_entries)

        curated_entries = [
            entry
            for entry in curated_entries
            if _entry_matches_filters(entry, year_filter, language_filter, rating_threshold_value)
        ]
        curated_entries.sort(key=lambda entry: entry.get("_curated_index", 0))
        curated_entries = curated_entries[:GENRE_RESULT_LIMIT]

        total_needed = min(GENRE_RESULT_LIMIT, page * GENRE_PAGE_SIZE)
        curated_total = len(curated_entries)
        dynamic_required = max(0, total_needed - curated_total)

        dynamic_cache_key = (
            f"genre:dynamic-pool:{lower_genre_name}:{year_filter or ''}:{language_filter or ''}:"
            f"{rating_threshold_value if rating_threshold_value is not None else 'any'}"
        )
        dynamic_pool = _normalise_entries(_load_json_list(fetch_from_cache(cache_client, dynamic_cache_key)), curated_lookup)

        seen_ids = {entry["imdbID"].lower() for entry in curated_entries if entry.get("imdbID")}
        seen_ids.update({entry["imdbID"].lower() for entry in dynamic_pool if entry.get("imdbID")})

        max_dynamic_allowed = max(0, GENRE_RESULT_LIMIT - curated_total)
        if dynamic_required > len(dynamic_pool) and len(dynamic_pool) < max_dynamic_allowed:
            additional_needed = min(
                dynamic_required - len(dynamic_pool),
                max_dynamic_allowed - len(dynamic_pool),
            )
            new_entries = _fetch_random_high_rated_entries(
                cache_client,
                omdb_api_key,
                genre_name,
                additional_needed,
                seen_ids,
                year_filter,
                language_filter,
                rating_threshold_value,
                curated_lookup,
            )
            if new_entries:
                dynamic_pool.extend(new_entries)
                store_in_cache(cache_client, dynamic_cache_key, dynamic_pool)

        dynamic_pool = dynamic_pool[:max(0, GENRE_RESULT_LIMIT - curated_total)]
        ordered_entries = curated_entries + _sort_entries(dynamic_pool, sort_mode)
        if not ordered_entries:
            return jsonify({"genre": genre_name, "results": [], "message": "No results found."}), 404

        total_count = len(ordered_entries)
        total_pages = max(1, math.ceil(total_count / GENRE_PAGE_SIZE))
        if page > total_pages:
            page = total_pages

        start_index = (page - 1) * GENRE_PAGE_SIZE
        end_index = start_index + GENRE_PAGE_SIZE
        page_results = ordered_entries[start_index:end_index]

        potential_more = (
            total_count < GENRE_RESULT_LIMIT and page < GENRE_MAX_PAGES
        )
        if potential_more and total_pages <= page:
            total_pages = page + 1

        response_body = {
            "genre": genre_name,
            "page": page,
            "per_page": GENRE_PAGE_SIZE,
            "filters": {
                "year": year_filter,
                "language": language_filter,
                "rating": rating_threshold_value,
                "sort": sort_mode,
            },
            "results": [_clean_entry(entry) for entry in page_results],
            "total_count": total_count,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": (page < total_pages) or potential_more,
            "cached": False,
        }
        store_in_cache(cache_client, cache_key, response_body)
        return jsonify(response_body)

    return bp
