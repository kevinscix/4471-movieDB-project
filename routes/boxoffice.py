import json
from typing import Any, Dict, List

from flask import Blueprint, current_app, jsonify, request

from services.omdb import BOX_OFFICE_SEED_TERMS, DEFAULT_BOX_OFFICE_IDS, GENRE_CURATED_IDS, average_rating, expand_search_terms, extract_ratings, fetch_movie_details, omdb_search_request, parse_box_office_value, parse_int_param
from utils.cache import fetch_from_cache, store_in_cache


def create_boxoffice_blueprint(cache_client, omdb_api_key: str) -> Blueprint:
    bp = Blueprint("boxoffice", __name__, url_prefix="/api")

    @bp.route("/boxoffice/top")
    def box_office_top() -> Any:
        query = request.args.get("q", "").strip()
        page = parse_int_param(request.args.get("page"), 1, minimum=1, maximum=20)
        per_page = parse_int_param(request.args.get("per_page"), 10, minimum=5, maximum=20)
        genre_filter = (request.args.get("genre") or "").strip()
        sort_mode = request.args.get("sort") or "box_office_desc"

        query_token = (query or "default").strip().lower() or "default"
        filter_token = (genre_filter or "any").strip().lower() or "any"
        cache_filter_token = filter_token if not query else "any"
        dataset_cache_key = f"boxoffice:dataset:{query_token}:{cache_filter_token}"
        cached_payload = fetch_from_cache(cache_client, dataset_cache_key)
        dataset_cached = False
        base_results: List[Dict[str, Any]] = []
        if cached_payload is not None:
            try:
                data = cached_payload if isinstance(cached_payload, dict) else json.loads(cached_payload)
                base_results = data.get("results", [])
                dataset_cached = True
            except Exception:
                current_app.logger.warning("Invalid cached box office dataset for %s", dataset_cache_key)

        if not base_results:
            candidates: List[Dict[str, str]] = []
            seen_identifiers: Dict[str, bool] = {}

            def add_candidate(item: Dict[str, str]) -> None:
                identifier = item.get("imdbID") or item.get("Title")
                if not identifier:
                    return
                key = identifier.strip().lower()
                if not key or seen_identifiers.get(key):
                    return
                title = item.get("Title") or ""
                if not query and genre_filter and genre_filter.lower() in title.lower():
                    return
                seen_identifiers[key] = True
                candidates.append(item)

            def fetch_candidates(term: str, max_pages: int = 5, limit: int = 200) -> None:
                for source_page in range(1, max_pages + 1):
                    if len(candidates) >= limit:
                        return
                    payload = omdb_search_request(
                        omdb_api_key, term, source_page, current_app.logger, media_type="movie"
                    )
                    if not payload or payload.get("Response") != "True":
                        break
                    for entry in payload.get("Search", []):
                        add_candidate(entry)

            if query:
                fetch_candidates(query, max_pages=5, limit=80)
            else:
                for imdb_id in DEFAULT_BOX_OFFICE_IDS:
                    add_candidate({"imdbID": imdb_id})
                if genre_filter:
                    curated = GENRE_CURATED_IDS.get(genre_filter.lower())
                    if curated:
                        for imdb_id in curated:
                            add_candidate({"imdbID": imdb_id})
                    genre_terms = expand_search_terms(genre_filter) or [genre_filter]
                    genre_terms.extend(
                        [
                            f"{genre_filter} movie",
                            f"{genre_filter} film",
                            f"{genre_filter} blockbuster",
                        ]
                    )
                    seen_term: Dict[str, bool] = {}
                    dedup_terms: List[str] = []
                    for term in genre_terms:
                        normalized = term.lower()
                        if normalized and not seen_term.get(normalized):
                            seen_term[normalized] = True
                            dedup_terms.append(term)
                    for term in dedup_terms:
                        fetch_candidates(term, max_pages=5, limit=250)
                else:
                    for seed in BOX_OFFICE_SEED_TERMS:
                        fetch_candidates(seed, max_pages=4, limit=250)

            base_results = []
            for candidate in candidates:
                identifier = candidate.get("imdbID") or candidate.get("Title")
                if not identifier:
                    continue
                detail, detail_cached = fetch_movie_details(cache_client, omdb_api_key, identifier)
                if not detail:
                    continue

                box_value = parse_box_office_value(detail.get("BoxOffice"))
                ratings = extract_ratings(detail)

                base_results.append(
                    {
                        "title": detail.get("Title"),
                        "imdbID": detail.get("imdbID"),
                        "year": detail.get("Year"),
                        "poster": detail.get("Poster"),
                        "box_office": box_value,
                        "box_office_label": detail.get("BoxOffice", "N/A"),
                        "ratings": ratings,
                        "average_rating": average_rating(ratings),
                        "director": detail.get("Director"),
                        "genre": detail.get("Genre"),
                        "financials": {
                            "box_office_raw": detail.get("BoxOffice", "N/A"),
                            "released": detail.get("Released"),
                            "runtime": detail.get("Runtime"),
                        },
                        "cached": detail_cached,
                    }
                )

            base_results.sort(key=lambda item: item["box_office"], reverse=True)
            store_in_cache(cache_client, dataset_cache_key, {"results": base_results})

        filtered_results = list(base_results)
        if genre_filter:
            genre_lower = genre_filter.lower()
            filtered_results = [
                item for item in filtered_results if genre_lower in (item.get("genre") or "").lower()
            ]

        def rating_value(entry: Dict[str, Any]) -> float:
            avg = entry.get("average_rating")
            return float(avg) if avg is not None else -1.0

        if sort_mode == "box_office_asc":
            filtered_results.sort(key=lambda item: (item["box_office"], (item.get("title") or "").lower()))
        elif sort_mode == "rating_desc":
            filtered_results.sort(
                key=lambda item: (rating_value(item), item["box_office"], (item.get("title") or "").lower()),
                reverse=True,
            )
        elif sort_mode == "rating_asc":
            filtered_results.sort(
                key=lambda item: (rating_value(item), item["box_office"], (item.get("title") or "").lower())
            )
        elif sort_mode == "title_asc":
            filtered_results.sort(key=lambda item: (item.get("title") or "").lower())
        elif sort_mode == "title_desc":
            filtered_results.sort(key=lambda item: (item.get("title") or "").lower(), reverse=True)
        else:
            filtered_results.sort(
                key=lambda item: (item["box_office"], rating_value(item), (item.get("title") or "").lower()),
                reverse=True,
            )

        if genre_filter and not query:
            curated_ids = GENRE_CURATED_IDS.get(genre_filter.lower(), [])[:10]
            curated_lookup = {imdb_id.lower(): idx for idx, imdb_id in enumerate(curated_ids)}
            curated_results: List[Dict[str, Any]] = []
            curated_seen: Dict[str, bool] = {}
            for imdb_id in curated_ids:
                match = next(
                    (
                        item
                        for item in filtered_results
                        if (item.get("imdbID") or "").lower() == imdb_id.lower()
                    ),
                    None,
                )
                if match and not curated_seen.get(imdb_id.lower()):
                    curated_results.append(match)
                    curated_seen[imdb_id.lower()] = True
            remaining_results = [
                item
                for item in filtered_results
                if (item.get("imdbID") or "").lower() not in curated_seen
            ]
            filtered_results = curated_results + remaining_results

        total_count = len(filtered_results)
        if not total_count:
            page = 1
        total_pages = (total_count + per_page - 1) // per_page if total_count else 1
        if total_count and page > total_pages:
            page = total_pages
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        page_results = filtered_results[start_index:end_index] if total_count else []
        has_prev = page > 1 and total_count > 0
        has_next = end_index < total_count

        chart_data = [
            {"title": item["title"], "box_office": item["box_office"]}
            for item in filtered_results[:10]
        ]
        total_box_office = sum(item["box_office"] for item in filtered_results)
        avg_box_office = round(total_box_office / total_count, 2) if total_count else 0

        recommended: List[Dict[str, Any]] = []
        if filtered_results:
            lead_director = filtered_results[0].get("director")
            if lead_director:
                recommended = [
                    item for item in filtered_results if item.get("director") == lead_director
                ][1:6]
            if not recommended and len(filtered_results) > 1:
                recommended = filtered_results[1:6]

        response_body = {
            "query": query or "top box office",
            "page": page,
            "per_page": per_page,
            "results": page_results,
            "total_count": total_count,
            "total_pages": total_pages,
            "has_prev": has_prev,
            "has_next": has_next,
            "chart": chart_data,
            "recommended": recommended,
            "metrics": {
                "total_box_office": total_box_office,
                "average_box_office": avg_box_office,
                "top_box_office": filtered_results[0]["box_office_label"] if filtered_results else "N/A",
            },
            "filters": {"genre": genre_filter or None, "sort": sort_mode},
            "cached": dataset_cached,
        }

        return jsonify(response_body)

    return bp
