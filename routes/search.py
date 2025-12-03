from typing import Any, Dict, List

from flask import Blueprint, jsonify, request, g, current_app

from services.omdb import (
    average_rating,
    expand_search_terms,
    extract_ratings,
    fetch_movie_details,
    omdb_search_request,
    parse_int_param,
    similarity_score,
)
from utils.cache import fetch_from_cache, store_in_cache


def create_search_blueprint(cache_client, omdb_api_key: str) -> Blueprint:
    bp = Blueprint("search", __name__, url_prefix="/api")

    @bp.route("/search")
    def search() -> Any:
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"error": "Query parameter 'q' is required."}), 400
        if len(query) > 100:
            return jsonify({"error": "Query must be 100 characters or fewer."}), 400

        page = parse_int_param(request.args.get("page"), 1, minimum=1, maximum=10)
        per_page = parse_int_param(request.args.get("per_page"), 10, minimum=5, maximum=10)
        media_type = request.args.get("type")
        year_filter = request.args.get("year")
        language_filter = request.args.get("language")
        sort_mode = request.args.get("sort") or "relevance"

        if media_type and media_type not in {"movie", "series", "episode"}:
            return jsonify({"error": "type must be one of movie, series, episode"}), 400
        if year_filter and not year_filter.isdigit():
            return jsonify({"error": "year must be numeric"}), 400
        if sort_mode not in {"relevance", "recent", "rating"}:
            return jsonify({"error": "sort must be one of relevance, recent, rating"}), 400

        cache_key = f"omdb:search:{query.lower()}:{page}:{per_page}:{media_type}:{year_filter}:{language_filter}:{sort_mode}"
        cached_payload = fetch_from_cache(cache_client, cache_key)
        if cached_payload is not None:
            data = cached_payload if isinstance(cached_payload, dict) else None
            if not data:
                try:
                    import json

                    data = json.loads(cached_payload)
                except Exception:
                    data = None
            if data:
                data["cached"] = True
                return jsonify(data)

        start_index = (page - 1) * per_page
        target_results = start_index + (per_page * 2)

        variants = expand_search_terms(query)
        aggregated: List[Dict[str, Any]] = []
        seen_ids: Dict[str, bool] = {}
        total_hints: List[int] = []
        maybe_more = False
        had_payload = False

        max_source_pages = min(page + 1, 3)
        for term in variants:
            for source_page in range(1, max_source_pages + 1):
                if aggregated and source_page > 1 and len(aggregated) >= target_results:
                    break
                payload = omdb_search_request(
                    omdb_api_key,
                    term,
                    source_page,
                    current_app.logger,
                    media_type=media_type,
                    year=year_filter,
                )
                if not payload or payload.get("Response") != "True":
                    break
                had_payload = True
                try:
                    total_hint = int(payload.get("totalResults", "0") or 0)
                except (TypeError, ValueError):
                    total_hint = 0
                total_hints.append(total_hint)
                if total_hint > source_page * 10:
                    maybe_more = True
                for item in payload.get("Search", []):
                    identifier = item.get("imdbID") or item.get("Title")
                    if not identifier or identifier in seen_ids:
                        continue
                    seen_ids[identifier] = True
                    aggregated.append(
                        {
                            "title": item.get("Title"),
                            "year": item.get("Year"),
                            "poster": item.get("Poster"),
                            "imdbID": item.get("imdbID"),
                        }
                    )
                if len(aggregated) >= target_results:
                    break
            if len(aggregated) >= target_results:
                break

        if not aggregated:
            # Fallback: drop trailing 's' or add one to broaden match.
            alt_query = query[:-1] if query.lower().endswith("s") else f"{query}s"
            payload = omdb_search_request(
                omdb_api_key, alt_query, 1, current_app.logger, media_type=media_type, year=year_filter
            )
            if payload and payload.get("Response") == "True":
                aggregated = [
                    {
                        "title": item.get("Title"),
                        "year": item.get("Year"),
                        "poster": item.get("Poster"),
                        "imdbID": item.get("imdbID"),
                    }
                    for item in payload.get("Search", [])
                ]

        if not aggregated:
            result = {
                "results": [],
                "message": "No results found.",
                "query": query,
                "page": page,
                "per_page": per_page,
                "cached": False,
            }
            store_in_cache(cache_client, cache_key, result)
            return jsonify(result)

        # Score, enrich, and sort before pagination so sort modes can be applied globally.
        scored: List[Dict[str, Any]] = []
        for item in aggregated:
            score = similarity_score(query, item.get("title", ""))
            if year_filter and str(item.get("year")) == str(year_filter):
                score += 0.5
            item["_sort_score"] = score
            scored.append(item)

        enriched_results: List[Dict[str, Any]] = []
        for item in scored:
            identifier = item.get("imdbID") or item.get("title")
            detail, _ = fetch_movie_details(cache_client, omdb_api_key, identifier)
            if not detail:
                continue
            if year_filter and str(detail.get("Year", "")).strip() != str(year_filter):
                continue
            if language_filter and language_filter.lower() not in (detail.get("Language") or "").lower():
                continue
            ratings = extract_ratings(detail)
            try:
                imdb_rating_val = float(detail.get("imdbRating")) if detail.get("imdbRating") not in (None, "", "N/A") else 0.0
            except ValueError:
                imdb_rating_val = 0.0
            try:
                year_val = int(str(detail.get("Year") or "0")[:4])
            except ValueError:
                year_val = 0
            enriched_results.append(
                {
                    **item,
                    "plot": detail.get("Plot"),
                    "genre": detail.get("Genre"),
                    "imdbRating": detail.get("imdbRating"),
                    "boxOffice": detail.get("BoxOffice"),
                    "ratings": ratings,
                    "average_rating": average_rating(ratings),
                    "match_score": item.get("_sort_score", 0),
                    "_rating_val": imdb_rating_val,
                    "_year_val": year_val,
                }
            )

        def sort_key(entry: Dict[str, Any]) -> Any:
            if sort_mode == "recent":
                return (entry.get("_year_val", 0), entry.get("match_score", 0))
            if sort_mode == "rating":
                return (entry.get("_rating_val", 0), entry.get("match_score", 0))
            return (entry.get("match_score", 0), entry.get("_year_val", 0))

        enriched_results.sort(key=sort_key, reverse=True)

        page_results = enriched_results[start_index : start_index + per_page]
        total_results = len(enriched_results)
        has_next = total_results > start_index + per_page
        total_pages = (total_results + per_page - 1) // per_page if total_results else 1
        enriched_results = page_results

        result = {
            "query": query,
            "page": page,
            "per_page": per_page,
            "results": enriched_results,
            "total_results": total_results,
            "total_pages": total_pages,
            "has_next": has_next,
            "has_prev": page > 1,
            "variants": variants,
            "filters": {
                "type": media_type,
                "year": year_filter,
                "language": language_filter,
            },
            "cached": False,
            "request_id": getattr(g, "request_id", None),
        }
        duration_ms = None
        try:
            duration_ms = round((g.start_time and ( __import__('time').perf_counter() - g.start_time) ) * 1000, 2)
        except Exception:
            pass
        current_app.logger.info(
            "search req=%s q=%s page=%s per_page=%s variants=%s filters=%s results=%s duration_ms=%s",
            getattr(g, "request_id", None),
            query,
            page,
            per_page,
            variants,
            {"type": media_type, "year": year_filter, "language": language_filter},
            len(enriched_results),
            duration_ms,
        )
        store_in_cache(cache_client, cache_key, result)
        return jsonify(result)

    return bp
