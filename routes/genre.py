from typing import Any, Dict, List, Optional

from flask import Blueprint, current_app, jsonify, request

from services.tmdb import tmdb_discover_movies, tmdb_external_ids, tmdb_list_genres
from utils.cache import fetch_from_cache, store_in_cache
from services.omdb import (
    parse_int_param,
    fetch_movie_details,
    extract_ratings,
    average_rating,
    parse_box_office_value,
)

GENRE_PAGE_SIZE = 10
GENRE_MAX_PAGES = 10


def create_genre_blueprint(cache_client, omdb_api_key: str, tmdb_api_key: Optional[str]) -> Blueprint:
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
        return jsonify({"error": "Not implemented for TMDb mode."}), 501

    @bp.route("/genre/<genre_name>")
    def browse_genre(genre_name: str) -> Any:
        if not tmdb_api_key:
            return jsonify({"error": "TMDB_API_KEY is not configured"}), 500

        page = parse_int_param(request.args.get("page"), 1, minimum=1, maximum=GENRE_MAX_PAGES)
        year_filter = request.args.get("year")
        language_filter = request.args.get("language")
        rating_threshold = request.args.get("rating")
        sort_mode = request.args.get("sort") or "rating_desc"
        sort_map = {
            "rating_desc": "vote_average.desc",
            "rating_asc": "vote_average.asc",
            "year_desc": "release_date.desc",
            "year_asc": "release_date.asc",
            "title_asc": "original_title.asc",
            "title_desc": "original_title.desc",
            "boxoffice_desc": "popularity.desc",  # will re-sort locally
            "boxoffice_asc": "popularity.desc",
        }
        sort_by = sort_map.get(sort_mode, "popularity.desc")

        try:
            rating_threshold_value = float(rating_threshold) if rating_threshold else None
        except ValueError:
            return jsonify({"error": "rating must be numeric"}), 400

        # Normalize language to TMDb codes (ISO 639-1)
        language_map = {
            "english": "en",
            "en": "en",
            "spanish": "es",
            "es": "es",
            "french": "fr",
            "fr": "fr",
            "german": "de",
            "de": "de",
            "hindi": "hi",
            "hi": "hi",
            "japanese": "ja",
            "ja": "ja",
            "korean": "ko",
            "ko": "ko",
            "chinese": "zh",
            "zh": "zh",
        }
        if language_filter:
            language_filter = language_map.get(language_filter.lower(), language_filter.lower())

        cache_key = (
            f"genre:tmdb:{genre_name.lower()}:{page}:{year_filter}:{language_filter}:"
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

        tmdb_genres = tmdb_list_genres()
        genre_id = tmdb_genres.get(genre_name.lower())
        if not genre_id:
            return jsonify({"error": f"Genre '{genre_name}' not found in TMDb"}), 404

        tmdb_response = tmdb_discover_movies(
            genre_id=genre_id,
            page=page,
            sort_by=sort_by,
            year=year_filter,
            language=language_filter,
            min_votes=200,  # avoid tiny unknown titles
        )
        if not tmdb_response or not tmdb_response.get("results"):
            return jsonify({"genre": genre_name, "results": [], "message": "No results found."}), 404

        results: List[Dict[str, Any]] = []
        for item in tmdb_response.get("results", []):
            tmdb_id = item.get("id")
            imdb_id = None
            if tmdb_id:
                ids = tmdb_external_ids(tmdb_id)
                if ids:
                    imdb_id = ids.get("imdb_id")

            rating_val = item.get("vote_average") or 0.0
            release_date = item.get("release_date") or ""
            year_val = release_date.split("-")[0] if release_date else ""

            detail_avg = None
            detail_ratings = {}
            box_office_label = None
            box_office_value = 0
            if imdb_id:
                detail, _, _ = fetch_movie_details(cache_client, omdb_api_key, imdb_id)
                if detail:
                    detail_ratings = extract_ratings(detail)
                    detail_avg = average_rating(detail_ratings)
                    box_office_label = detail.get("BoxOffice")
                    box_office_value = parse_box_office_value(box_office_label)

            effective_rating = detail_avg if detail_avg is not None else rating_val
            if rating_threshold_value is not None and effective_rating < rating_threshold_value:
                continue

            results.append(
                {
                    "title": item.get("title") or item.get("original_title"),
                    "imdbID": imdb_id,
                    "year": year_val,
                    "poster": f"https://image.tmdb.org/t/p/w500{item.get('poster_path')}" if item.get("poster_path") else None,
                    "genres": genre_name,
                    "imdbRating": detail_ratings.get("Internet Movie Database") if detail_ratings else None,
                    "average_rating": effective_rating,
                    "language": item.get("original_language"),
                    "plot": item.get("overview"),
                    "boxOffice": box_office_label,
                    "_box_office_val": box_office_value,
                }
            )

        total_results = tmdb_response.get("total_results", len(results))
        total_pages = tmdb_response.get("total_pages", 1)

        def sort_key(x: Dict[str, Any]):
            if sort_mode.startswith("boxoffice"):
                return (x.get("_box_office_val", 0), x.get("average_rating", 0), x.get("year") or 0)
            if sort_mode.startswith("rating"):
                return (x.get("average_rating", 0), x.get("_box_office_val", 0), x.get("year") or 0)
            if sort_mode.startswith("year"):
                return (int(x.get("year") or 0), x.get("average_rating", 0), x.get("_box_office_val", 0))
            return (x.get("average_rating", 0), x.get("_box_office_val", 0), x.get("year") or 0)

        results.sort(key=sort_key, reverse=sort_mode.endswith("desc"))

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
            "results": results,
            "total_count": total_results,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "cached": False,
        }
        store_in_cache(cache_client, cache_key, response_body)
        return jsonify(response_body)

    return bp
