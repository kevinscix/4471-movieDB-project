from typing import Any, Dict, List

from flask import Blueprint, current_app, jsonify, request

from services.omdb import GENRE_CURATED_IDS, expand_search_terms, fetch_movie_details, omdb_search_request, parse_box_office_value, parse_int_param
from utils.cache import fetch_from_cache, store_in_cache


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
        page = parse_int_param(request.args.get("page"), 1, minimum=1, maximum=10)
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
                import json

                data = json.loads(cached_payload)
                data["cached"] = True
                return jsonify(data)
            except Exception:
                current_app.logger.warning("Invalid cached genre payload for %s", genre_name)

        page_size = 10
        max_candidates = page_size * 30
        source_results: List[Dict[str, Any]] = []
        seen_candidates: Dict[str, bool] = {}

        lower_genre_name = genre_name.lower()
        curated_ids = GENRE_CURATED_IDS.get(lower_genre_name, [])
        curated_lookup = {imdb_id.lower(): idx for idx, imdb_id in enumerate(curated_ids)}

        def add_candidate(item: Dict[str, Any]) -> bool:
            identifier = item.get("imdbID") or item.get("Title")
            if not identifier:
                return False
            key = identifier.lower()
            if seen_candidates.get(key):
                return False
            title = item.get("Title") or ""
            if lower_genre_name and title and lower_genre_name in title.lower():
                return False
            seen_candidates[key] = True
            source_results.append(item)
            return len(source_results) >= max_candidates

        limit_reached = False
        for imdb_id in curated_ids:
            if add_candidate({"imdbID": imdb_id}):
                limit_reached = True
                break

        if not limit_reached:
            base_variants = expand_search_terms(genre_name) or [genre_name]
            extended_variants = list(base_variants)
            extended_variants.extend(
                [
                    f"{genre_name} movie",
                    f"{genre_name} film",
                    f"{genre_name} blockbuster",
                    f"{genre_name} cinema",
                ]
            )
            seen_variant: Dict[str, bool] = {}
            ordered_variants: List[str] = []
            for term in extended_variants:
                normalized = term.lower().strip()
                if not normalized or seen_variant.get(normalized):
                    continue
                seen_variant[normalized] = True
                ordered_variants.append(term)
            for term in ordered_variants:
                for source_page in range(1, 6):
                    if limit_reached:
                        break
                    payload = omdb_search_request(omdb_api_key, term, source_page, current_app.logger)
                    if not payload or payload.get("Response") != "True":
                        break
                    for entry in payload.get("Search", []):
                        if add_candidate(entry):
                            limit_reached = True
                            break
                    if limit_reached:
                        break
                if limit_reached:
                    break

        if not source_results:
            return jsonify({"genre": genre_name, "results": [], "message": "No results found."}), 404

        detailed_entries: List[Dict[str, Any]] = []
        seen_details: Dict[str, bool] = {}
        for item in source_results:
            identifier = item.get("imdbID") or item.get("Title")
            if not identifier:
                continue
            key = identifier.lower()
            if seen_details.get(key):
                continue
            detail, _, _ = fetch_movie_details(cache_client, omdb_api_key, identifier)
            if not detail:
                continue
            genre_field = detail.get("Genre", "") or ""
            if lower_genre_name not in genre_field.lower():
                continue
            if year_filter and not str(detail.get("Year", "")).startswith(str(year_filter)):
                continue
            if language_filter and language_filter.lower() not in (detail.get("Language") or "").lower():
                continue
            imdb_rating_str = detail.get("imdbRating")
            try:
                rating_value = (
                    float(imdb_rating_str)
                    if imdb_rating_str not in (None, "", "N/A")
                    else 0.0
                )
            except ValueError:
                rating_value = 0.0
            if rating_threshold_value is not None and rating_value < rating_threshold_value:
                continue
            box_office_value = parse_box_office_value(detail.get("BoxOffice"))
            try:
                year_value = int(str(detail.get("Year") or "0")[:4])
            except ValueError:
                year_value = 0

            detailed_entries.append(
                {
                    "title": detail.get("Title"),
                    "imdbID": detail.get("imdbID"),
                    "year": detail.get("Year"),
                    "poster": detail.get("Poster"),
                    "genres": genre_field,
                    "imdbRating": detail.get("imdbRating"),
                    "average_rating": rating_value if rating_value > 0 else None,
                    "language": detail.get("Language"),
                    "boxOffice": detail.get("BoxOffice"),
                    "_rating_val": rating_value,
                    "_box_office_val": box_office_value,
                    "_year_val": year_value,
                    "_curated": key in curated_lookup,
                }
            )
            seen_details[key] = True

        if not detailed_entries:
            return jsonify({"genre": genre_name, "results": [], "message": "No results found."}), 404

        curated_entries = [
            entry
            for entry in detailed_entries
            if entry["_curated"]
        ]
        curated_entries.sort(
            key=lambda entry: curated_lookup.get((entry.get("imdbID") or "").lower(), 0)
        )
        curated_entries = curated_entries[:page_size]
        curated_ids_present = {entry.get("imdbID", "").lower() for entry in curated_entries}

        other_entries = [
            entry for entry in detailed_entries if (entry.get("imdbID") or "").lower() not in curated_ids_present
        ]

        def sort_key(entry: Dict[str, Any]):
            title_key = (entry.get("title") or "").lower()
            if sort_mode == "rating_asc":
                return (entry["_rating_val"], entry["_box_office_val"], entry["_year_val"], title_key)
            if sort_mode == "rating_desc":
                return (entry["_rating_val"], entry["_box_office_val"], entry["_year_val"], title_key)
            if sort_mode == "year_asc":
                return (entry["_year_val"], entry["_rating_val"], entry["_box_office_val"], title_key)
            if sort_mode == "year_desc":
                return (entry["_year_val"], entry["_rating_val"], entry["_box_office_val"], title_key)
            if sort_mode == "title_asc":
                return title_key
            if sort_mode == "title_desc":
                return title_key
            return (entry["_rating_val"], entry["_box_office_val"], entry["_year_val"], title_key)

        reverse = sort_mode in {"rating_desc", "year_desc", "title_desc"}
        other_entries.sort(key=sort_key, reverse=reverse)

        ordered_entries = curated_entries + other_entries
        total_count = len(ordered_entries)
        if total_count == 0:
            return jsonify({"genre": genre_name, "results": [], "message": "No results found."}), 404

        total_pages = max(1, (total_count + page_size - 1) // page_size)
        if page > total_pages:
            page = total_pages
        start_index = (page - 1) * page_size
        page_results = ordered_entries[start_index : start_index + page_size]

        def clean_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
            return {k: v for k, v in entry.items() if not k.startswith("_")}

        serialized_results = [clean_entry(entry) for entry in page_results]

        response_body = {
            "genre": genre_name,
            "page": page,
            "per_page": page_size,
            "filters": {
                "year": year_filter,
                "language": language_filter,
                "rating": rating_threshold_value,
                "sort": sort_mode,
            },
            "results": serialized_results,
            "total_count": total_count,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "cached": False,
        }
        store_in_cache(cache_client, cache_key, response_body)
        return jsonify(response_body)

    return bp
