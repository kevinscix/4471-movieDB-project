from typing import Any

from flask import Blueprint, current_app, jsonify, render_template

from services.omdb import average_rating, extract_ratings, fetch_movie_details, find_similar_movies, parse_box_office_value
from utils.cache import fetch_from_cache, store_in_cache


def create_movie_blueprint(cache_client, omdb_api_key: str) -> Blueprint:
    bp = Blueprint("movie", __name__)

    def _movie_payload(imdb_id: str) -> Any:
        identifier = imdb_id.strip()
        detail, cached_detail = fetch_movie_details(cache_client, omdb_api_key, identifier)
        if not detail:
            return None, None

        ratings = extract_ratings(detail)
        avg_rating = average_rating(ratings)
        box_office_label = detail.get("BoxOffice", "N/A")
        box_office_value = parse_box_office_value(box_office_label)

        similar_cache_key = f"similar:{identifier}"
        cached_similar = fetch_from_cache(cache_client, similar_cache_key)
        if cached_similar:
            similar = cached_similar if isinstance(cached_similar, list) else None
            if similar is None:
                try:
                    import json

                    similar = json.loads(cached_similar)
                except Exception:
                    current_app.logger.warning("Invalid cached similar payload for %s", identifier)
                    similar = []
        else:
            similar = find_similar_movies(detail, cache_client, omdb_api_key)
            store_in_cache(cache_client, similar_cache_key, similar)

        movie_payload = {
            "title": detail.get("Title"),
            "year": detail.get("Year"),
            "poster": detail.get("Poster"),
            "runtime": detail.get("Runtime"),
            "genre": detail.get("Genre"),
            "plot": detail.get("Plot"),
            "director": detail.get("Director"),
            "writer": detail.get("Writer"),
            "actors": detail.get("Actors"),
            "box_office_label": box_office_label,
            "box_office_value": box_office_value,
            "imdbID": detail.get("imdbID"),
            "imdbRating": detail.get("imdbRating"),
            "released": detail.get("Released"),
            "language": detail.get("Language"),
            "awards": detail.get("Awards"),
        }

        payload = {
            "movie": movie_payload,
            "ratings": ratings,
            "average_rating": avg_rating,
            "similar_movies": similar,
            "cached": cached_detail,
        }
        return payload, None

    @bp.route("/movie/<imdb_id>")
    def movie_detail(imdb_id: str) -> Any:
        payload, error = _movie_payload(imdb_id)
        if payload is None:
            return jsonify({"error": "Movie not found"}), 404
        return jsonify(payload)

    @bp.route("/movie/<imdb_id>/view")
    def movie_view(imdb_id: str) -> Any:
        payload, error = _movie_payload(imdb_id)
        if payload is None:
            return render_template("movie_detail.html", movie=None, ratings={}, average_rating=None, similar_movies=[], cached=False)
        return render_template(
            "movie_detail.html",
            movie=payload["movie"],
            ratings={k: v if v is not None else "N/A" for k, v in payload["ratings"].items()},
            average_rating=payload["average_rating"],
            similar_movies=payload["similar_movies"],
            cached=payload["cached"],
        )

    return bp
