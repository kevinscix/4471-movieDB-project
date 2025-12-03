import json
import logging
import os
from typing import Any, Optional

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None


def initialise_cache(logger: logging.Logger):
    if redis is None:
        logger.warning("redis package is not available; caching disabled")
        return None
    host = os.getenv("REDIS_HOST", "redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    password = os.getenv("REDIS_PASSWORD")
    client = redis.Redis(host=host, port=port, password=password, decode_responses=True)
    try:
        client.ping()
        logger.info("Connected to Redis at %s:%s", host, port)
        return client
    except redis.RedisError as exc:
        logger.warning("Redis unavailable (%s); proceeding without cache", exc)
        return None


def fetch_from_cache(cache_client: Optional["redis.Redis"], key: str) -> Optional[str]:
    if cache_client is None:
        return None
    try:
        return cache_client.get(key)
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to fetch from cache: %s", exc)
        return None


def store_in_cache(cache_client: Optional["redis.Redis"], key: str, value: Any, ttl: int = 600) -> None:
    if cache_client is None:
        return
    try:
        cache_client.setex(key, ttl, json.dumps(value))
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to store in cache: %s", exc)
