import json
import logging
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

import requests

OMDB_BASE_URL = "http://www.omdbapi.com/"
DEFAULT_BOX_OFFICE_IDS = [
    "tt0499549",  # Avatar
    "tt4154796",  # Avengers: Endgame
    "tt0120338",  # Titanic
    "tt2488496",  # Star Wars: The Force Awakens
    "tt4154756",  # Avengers: Infinity War
    "tt0369610",  # Jurassic World
    "tt6105098",  # The Lion King (2019)
    "tt0848228",  # The Avengers
    "tt2820852",  # Furious 7
    "tt4520988",  # Frozen II
]

GENRE_CURATED_IDS = {
    "action": [
        "tt4154796",
        "tt0848228",
        "tt0468569",
        "tt0133093",
        "tt1392190",
        "tt1375666",
        "tt2911666",
        "tt4154756",
        "tt1825683",
        "tt4912910",
    ],
    "adventure": [
        "tt0120737",
        "tt0167260",
        "tt0167261",
        "tt2488496",
        "tt0107290",
        "tt0363771",
        "tt0120915",
        "tt1201607",
        "tt0325980",
        "tt0848228",
    ],
    "animation": [
        "tt4633694",
        "tt2096673",
        "tt2948356",
        "tt2294629",
        "tt3521164",
        "tt0317705",
        "tt0266543",
        "tt2380307",
        "tt1979376",
        "tt1323594",
    ],
    "comedy": [
        "tt0107048",
        "tt0088763",
        "tt0106611",
        "tt1119646",
        "tt0357413",
        "tt0829482",
        "tt1478338",
        "tt0091042",
        "tt0118715",
        "tt0377092",
    ],
    "crime": [
        "tt0110912",
        "tt0114369",
        "tt0468569",
        "tt0137523",
        "tt0102926",
        "tt0099685",
        "tt0110413",
        "tt0208092",
        "tt0112384",
        "tt0068646",
    ],
    "drama": [
        "tt0111161",
        "tt0109830",
        "tt0172495",
        "tt0816692",
        "tt0120338",
        "tt2582802",
        "tt0209144",
        "tt0108052",
        "tt1853728",
        "tt0993846",
    ],
    "fantasy": [
        "tt0120737",
        "tt0167260",
        "tt0241527",
        "tt1201607",
        "tt0107290",
        "tt6139732",
        "tt4633694",
        "tt0363771",
        "tt0295297",
        "tt0304141",
    ],
    "horror": [
        "tt7784604",
        "tt1457767",
        "tt0081505",
        "tt2316204",
        "tt0100157",
        "tt0078748",
        "tt3385516",
        "tt0290673",
        "tt2568844",
        "tt0080761",
    ],
    "mystery": [
        "tt0482571",
        "tt1375666",
        "tt0114369",
        "tt0209144",
        "tt0137523",
        "tt0443706",
        "tt0114814",
        "tt1853728",
        "tt0327056",
        "tt0119174",
    ],
    "romance": [
        "tt0332280",
        "tt0120338",
        "tt0109830",
        "tt3783958",
        "tt3104988",
        "tt0147800",
        "tt0108160",
        "tt0993846",
        "tt0101761",
        "tt1825683",
    ],
    "sci-fi": [
        "tt0816692",
        "tt0088763",
        "tt1375666",
        "tt2488496",
        "tt0133093",
        "tt0080684",
        "tt1454468",
        "tt1856101",
        "tt0083658",
        "tt1182345",
    ],
    "thriller": [
        "tt0114369",
        "tt0482571",
        "tt0137523",
        "tt0266697",
        "tt1877830",
        "tt0114814",
        "tt0120586",
        "tt0167404",
        "tt1130884",
        "tt0468569",
    ],
}

BOX_OFFICE_SEED_TERMS = [
    "Avengers",
    "Star Wars",
    "Batman",
    "Spider-Man",
    "Mission Impossible",
    "Fast and Furious",
    "Jurassic",
    "Harry Potter",
    "Pixar",
    "James Bond",
]

KNOWN_GENRES = [
    "Action",
    "Adventure",
    "Animation",
    "Comedy",
    "Crime",
    "Documentary",
    "Drama",
    "Fantasy",
    "Horror",
    "Mystery",
    "Romance",
    "Sci-Fi",
    "Thriller",
]


def parse_box_office_value(box_office: Optional[str]) -> int:
    if not box_office or box_office == "N/A":
        return 0
    digits = "".join(ch for ch in box_office if ch.isdigit())
    return int(digits or 0)


def normalize_rating(source: str, value: str) -> Optional[float]:
    try:
        if source == "Internet Movie Database" and "/" in value:
            numerator, denominator = value.split("/")
            return (float(numerator) / float(denominator)) * 100
        if source == "Rotten Tomatoes" and value.endswith("%"):
            return float(value.strip("%"))
        if source == "Metacritic" and "/" in value:
            numerator, denominator = value.split("/")
            return (float(numerator) / float(denominator)) * 100
    except (ValueError, ZeroDivisionError):
        return None
    return None


def extract_ratings(detail: Dict[str, Any]) -> Dict[str, Optional[float]]:
    ratings: Dict[str, Optional[float]] = {
        "Internet Movie Database": None,
        "Rotten Tomatoes": None,
        "Metacritic": None,
    }
    for rating in detail.get("Ratings", []):
        source = rating.get("Source")
        value = rating.get("Value")
        if not source or not value:
            continue
        normalized = normalize_rating(source, value)
        if normalized is not None:
            ratings[source] = round(normalized, 2)
    return ratings


def average_rating(ratings: Dict[str, Optional[float]]) -> Optional[float]:
    values = [score for score in ratings.values() if score is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def parse_int_param(value: Optional[str], default: int, minimum: int = 1, maximum: int = 10) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        return default
    parsed = max(min(parsed, maximum), minimum)
    return parsed


def expand_search_terms(query: str) -> List[str]:
    normalized = query.strip()
    if not normalized:
        return []
    variants = [normalized]
    lower = normalized.lower()
    if lower.endswith("ies"):
        variants.append(normalized[:-3] + "y")
    elif lower.endswith("y"):
        variants.append(normalized[:-1] + "ies")
    if lower.endswith("s"):
        singular = normalized[:-1]
        if singular:
            variants.append(singular)
    else:
        variants.append(normalized + "s")
    seen: Dict[str, bool] = {}
    ordered: List[str] = []
    for item in variants:
        key = item.lower()
        if key in seen or not item:
            continue
        seen[key] = True
        ordered.append(item)
    return ordered


def similarity_score(a: str, b: str) -> float:
    """Compute fuzzy similarity ratio between two strings (0..1)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def omdb_search_request(
    omdb_api_key: str,
    term: str,
    page: int,
    logger: logging.Logger,
    media_type: Optional[str] = None,
    year: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    try:
        response = requests.get(
            OMDB_BASE_URL,
            params={
                "apikey": omdb_api_key,
                "s": term,
                "page": page,
                **({"type": media_type} if media_type else {}),
                **({"y": year} if year else {}),
            },
            timeout=3,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        logger.error("OMDb search failed for %s page %s: %s", term, page, exc)
    except ValueError:
        logger.error("OMDb search returned invalid JSON for %s page %s", term, page)
    return None


def fetch_movie_details(
    cache_client: Optional["redis.Redis"], omdb_api_key: str, identifier: str
) -> Tuple[Optional[Dict[str, Any]], bool, Optional[str]]:
    logger = logging.getLogger(__name__)
    cache_key = f"omdb:detail:{identifier.lower()}"
    if cache_client is not None:
        try:
            cached_payload = cache_client.get(cache_key)
            if cached_payload:
                return json.loads(cached_payload), True, None
        except Exception:
            pass

    params: Dict[str, Any] = {"apikey": omdb_api_key, "plot": "short"}
    if identifier.lower().startswith("tt"):
        params["i"] = identifier
    else:
        params["t"] = identifier

    try:
        response = requests.get(OMDB_BASE_URL, params=params, timeout=5)
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.RequestException as e:
        error_msg = "Network error while fetching movie details"
        logger.warning("Failed to fetch movie details for %s: %s", identifier, str(e))
        return None, False, error_msg
    except ValueError as e:
        error_msg = "Invalid response from OMDb API"
        logger.warning("Failed to parse JSON for %s: %s", identifier, str(e))
        return None, False, error_msg

    if payload.get("Response") != "True":
        error_msg = payload.get("Error", "Movie not found in OMDb database")
        logger.warning("Movie not found in OMDb for %s: %s", identifier, error_msg)
        return None, False, error_msg

    if cache_client is not None:
        try:
            cache_client.setex(cache_key, 600, json.dumps(payload))
        except Exception:
            pass
    return payload, False, None


def find_similar_movies(
    base_detail: Dict[str, Any],
    cache_client: Optional["redis.Redis"],
    omdb_api_key: str,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    primary_genre = (base_detail.get("Genre") or "").split(",")[0].strip()
    if not primary_genre:
        return []

    logger = logging.getLogger(__name__)
    payload = omdb_search_request(omdb_api_key, primary_genre, 1, logger)
    if not payload or payload.get("Response") != "True":
        return []

    similar: List[Dict[str, Any]] = []
    seen_ids = {base_detail.get("imdbID")}
    for item in payload.get("Search", []):
        identifier = item.get("imdbID") or item.get("Title")
        if not identifier or identifier in seen_ids:
            continue
        seen_ids.add(identifier)
        detail, _, _ = fetch_movie_details(cache_client, omdb_api_key, identifier)
        if not detail:
            continue
        ratings = extract_ratings(detail)
        similar.append(
            {
                "title": detail.get("Title"),
                "year": detail.get("Year"),
                "poster": detail.get("Poster"),
                "imdbID": detail.get("imdbID"),
                "genre": detail.get("Genre"),
                "imdbRating": detail.get("imdbRating"),
                "average_rating": average_rating(ratings),
            }
        )
        if len(similar) >= limit:
            break
    return similar
