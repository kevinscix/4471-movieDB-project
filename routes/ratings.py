from typing import Any, Dict, List

from flask import Blueprint, current_app, jsonify, request

from services.omdb import average_rating, extract_ratings, fetch_movie_details
from utils.cache import fetch_from_cache, store_in_cache


def create_ratings_blueprint(cache_client, omdb_api_key: str) -> Blueprint:
    bp = Blueprint("ratings", __name__, url_prefix="/api")

    @bp.route("/ratings/summary", methods=["GET", "POST"])
    def ratings_summary() -> Any:
        queries: List[str] = []
        ids: List[str] = []
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            queries = [t.strip() for t in body.get("titles", []) if isinstance(t, str) and t.strip()]
            ids = [i.strip() for i in body.get("ids", []) if isinstance(i, str) and i.strip()]
        else:
            titles_param = request.args.get("titles")
            if titles_param:
                queries.extend([t.strip() for t in titles_param.split(",") if t.strip()])
            single_title = request.args.get("title")
            if single_title:
                queries.append(single_title.strip())
            single_id = request.args.get("imdbID") or request.args.get("id")
            if single_id:
                ids.append(single_id.strip())

        targets = ids + queries
        if not targets:
            return (
                jsonify(
                    {
                        "error": "Provide a movie 'title'/'titles' or 'imdbID'/'ids' to summarize ratings."
                    }
                ),
                400,
            )

        summaries: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []

        for target in targets:
            summary_cache_key = f"rating:summary:{target.lower()}"
            cached_summary = fetch_from_cache(cache_client, summary_cache_key)
            if cached_summary is not None:
                try:
                    import json

                    data = json.loads(cached_summary)
                    data["cached"] = True
                    summaries.append(data)
                    continue
                except Exception:
                    current_app.logger.warning("Invalid rating summary cache for %s", target)

            detail, detail_cached = fetch_movie_details(cache_client, omdb_api_key, target)
            if not detail:
                errors.append({"target": target, "error": "Movie not found or unavailable."})
                continue

            source_ratings = extract_ratings(detail)
            average_score = average_rating(source_ratings)
            scores = [score for score in source_ratings.values() if score is not None]
            if len(scores) >= 2 and (max(scores) - min(scores)) > 5:
                current_app.logger.info(
                    "Rating discrepancy >5%% for %s (%s): %s",
                    detail.get("Title"),
                    detail.get("imdbID"),
                    source_ratings,
                )

            summary = {
                "title": detail.get("Title"),
                "imdbID": detail.get("imdbID"),
                "year": detail.get("Year"),
                "poster": detail.get("Poster"),
                "ratings": {k: v if v is not None else "N/A" for k, v in source_ratings.items()},
                "average": average_score,
                "cached": detail_cached,
            }
            summaries.append(summary)
            store_in_cache(cache_client, summary_cache_key, summary)

        response_body: Dict[str, Any] = {"results": summaries, "count": len(summaries)}
        if errors:
            response_body["errors"] = errors

        status_code = 200 if summaries else 404
        return jsonify(response_body), status_code

    return bp
