"""cache module."""

from __future__ import annotations

import hashlib
import shelve
from functools import wraps

from .constants import CACHE_PATH
from .logger import log


def persistent_cache(cache_name: str, ignore_kwargs: list | None = None):
    """Cache the results of decorated function to cache_file."""
    ignore_kwargs = ignore_kwargs or []

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create a unique key for the function call based on its arguments
            filtered_kwargs = {
                k: v for k, v in kwargs.items() if k not in ignore_kwargs
            }
            key = hashlib.md5((str(args) + str(filtered_kwargs)).encode()).hexdigest()  # noqa: S324
            CACHE_PATH.mkdir(exist_ok=True)
            with shelve.open(str(CACHE_PATH / cache_name)) as cache:  # noqa: S301
                # Check if the result is already cached
                if key in cache:
                    log.debug(f"Fetching from cache for key: {key}")
                    return cache[key]
                result = func(*args, **kwargs)
                cache[key] = result
                log.debug(f"Caching result for key: {key}")
                return result

        return wrapper

    return decorator
