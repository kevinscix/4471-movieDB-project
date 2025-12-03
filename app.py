import logging
import os
import time
import uuid
from typing import Any

from flask import Flask, g, render_template

from routes.boxoffice import create_boxoffice_blueprint
from routes.genre import create_genre_blueprint
from routes.movie import create_movie_blueprint
from routes.ratings import create_ratings_blueprint
from routes.search import create_search_blueprint
from services.omdb import KNOWN_GENRES
from utils.cache import initialise_cache


def create_app() -> Flask:
    app = Flask(__name__)
    app.logger.setLevel(logging.INFO)

    omdb_api_key = os.getenv("OMDB_API_KEY")
    if not omdb_api_key:
        raise RuntimeError("OMDB_API_KEY environment variable is required")

    tmdb_api_key = os.getenv("TMDB_API_KEY")

    cache_client = initialise_cache(app.logger)

    app.register_blueprint(create_search_blueprint(cache_client, omdb_api_key))
    app.register_blueprint(create_movie_blueprint(cache_client, omdb_api_key))
    app.register_blueprint(create_ratings_blueprint(cache_client, omdb_api_key))
    app.register_blueprint(create_genre_blueprint(cache_client, omdb_api_key, tmdb_api_key))
    app.register_blueprint(create_boxoffice_blueprint(cache_client, omdb_api_key, tmdb_api_key))

    @app.before_request
    def _assign_request_id() -> None:
        g.request_id = uuid.uuid4().hex
        g.start_time = time.perf_counter()

    @app.after_request
    def _add_request_id(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", "unknown")
        return response

    @app.route("/")
    def index() -> Any:
        return render_template("index.html")

    @app.route("/search")
    def search_page() -> Any:
        return render_template("index.html")

    @app.route("/ratings")
    def ratings_page() -> Any:
        return render_template("ratings.html")

    @app.route("/genres")
    def genres_page() -> Any:
        return render_template("genres.html", genres=KNOWN_GENRES)

    @app.route("/boxoffice")
    def boxoffice_page() -> Any:
        return render_template("boxoffice.html", genres=KNOWN_GENRES)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
