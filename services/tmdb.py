import logging
import os
from typing import Any, Dict, List, Optional

import requests

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_BASE = "https://api.themoviedb.org/3"


def tmdb_get(path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not TMDB_API_KEY:
        return None
    params = params or {}
    params["api_key"] = TMDB_API_KEY
    try:
        resp = requests.get(f"{TMDB_BASE}/{path}", params=params, timeout=3)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logging.getLogger(__name__).warning("TMDb request failed for %s: %s", path, exc)
        return None


def tmdb_list_genres() -> Dict[str, int]:
    """Return mapping of lowercased genre name -> TMDb genre id."""
    data = tmdb_get("genre/movie/list")
    if not data or "genres" not in data:
        return {}
    return {g["name"].lower(): g["id"] for g in data.get("genres", []) if g.get("id") and g.get("name")}


def tmdb_discover_movies(
    genre_id: int,
    page: int = 1,
    sort_by: str = "popularity.desc",
    year: Optional[str] = None,
    language: Optional[str] = None,
    min_votes: int = 0,
) -> Optional[Dict[str, Any]]:
    params: Dict[str, Any] = {
        "with_genres": genre_id,
        "page": page,
        "sort_by": sort_by,
        "include_adult": False,
    }
    if year:
        params["primary_release_year"] = year
    if language:
        params["with_original_language"] = language
    if min_votes > 0:
        params["vote_count.gte"] = min_votes
    return tmdb_get("discover/movie", params)


def tmdb_external_ids(movie_id: int) -> Optional[Dict[str, Any]]:
    return tmdb_get(f"movie/{movie_id}/external_ids")
