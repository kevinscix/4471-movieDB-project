import json
import logging
import os
from typing import Any, Dict, Optional

import requests
from flask import Flask, jsonify, render_template, request

try:
    import redis
except ImportError:  # pragma: no cover - redis is installed in runtime environment
    redis = None

def create_app() -> Flask:
    app = Flask(__name__)

    omdb_api_key = os.getenv("OMDB_API_KEY")
    if not omdb_api_key:
        raise RuntimeError("OMDB_API_KEY environment variable is required")

    cache_client = initialise_cache(app)

    @app.route("/")
    def index() -> str:
        return render_template("index.html")

    @app.route("/search")
    def search() -> Any:
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"error": "Query parameter 'q' is required."}), 400
        if len(query) > 100:
            return jsonify({"error": "Query must be 100 characters or fewer."}), 400

        cache_key = f"omdb:search:{query.lower()}"
        cached_payload = fetch_from_cache(cache_client, cache_key)
        if cached_payload is not None:
            data = json.loads(cached_payload)
            data["cached"] = True
            return jsonify(data)

        try:
            response = requests.get(
                "http://www.omdbapi.com/",
                params={"apikey": omdb_api_key, "s": query},
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.RequestException as exc:
            app.logger.error("OMDb API request failed: %s", exc)
            return (
                jsonify(
                    {
                        "error": "Unable to contact the movie service at the moment.",
                    }
                ),
                502,
            )
        except ValueError:
            app.logger.error("OMDb API returned invalid JSON")
            return (
                jsonify(
                    {
                        "error": "Received an unexpected response from the movie service.",
                    }
                ),
                502,
            )
        if payload.get("Response", "False") != "True":
            message = payload.get("Error", "No results found.")
            result = {"results": [], "message": message, "cached": False}
            store_in_cache(cache_client, cache_key, result)
            return jsonify(result)

        movies = [
            {
                "title": item.get("Title"),
                "year": item.get("Year"),
                "poster": item.get("Poster"),
                "imdbID": item.get("imdbID"),
            }
            for item in payload.get("Search", [])
        ]
        result = {"results": movies, "total_results": payload.get("totalResults"), "cached": False}
        store_in_cache(cache_client, cache_key, result)
        return jsonify(result)

    return app


def initialise_cache(app: Flask) -> Optional["redis.Redis"]:
    if redis is None:
        app.logger.warning("redis package is not available; caching disabled")
        return None

    host = os.getenv("REDIS_HOST", "redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    password = os.getenv("REDIS_PASSWORD")

    client = redis.Redis(host=host, port=port, password=password, decode_responses=True)
    try:
        client.ping()
        app.logger.info("Connected to Redis at %s:%s", host, port)
        return client
    except redis.RedisError as exc:
        app.logger.warning("Redis unavailable (%s); proceeding without cache", exc)
        return None


def fetch_from_cache(cache_client: Optional["redis.Redis"], key: str) -> Optional[str]:
    if cache_client is None:
        return None
    try:
        return cache_client.get(key)
    except redis.RedisError as exc:
        logging.getLogger(__name__).warning("Failed to fetch from Redis: %s", exc)
        return None


def store_in_cache(cache_client: Optional["redis.Redis"], key: str, value: Dict[str, Any]) -> None:
    if cache_client is None:
        return
    try:
        cache_client.setex(key, 600, json.dumps(value))
    except redis.RedisError as exc:
        logging.getLogger(__name__).warning("Failed to store in Redis: %s", exc)


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))