import asyncio
import random
import re
import time

from openai import RateLimitError


def _is_rate_limit(error):
    if isinstance(error, RateLimitError):
        return True

    response = getattr(error, "response", None)
    return getattr(response, "status_code", None) == 429


def _retry_delay(error, attempt):
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}

    retry_after_ms = headers.get("retry-after-ms")
    if retry_after_ms:
        return float(retry_after_ms) / 1000 + random.uniform(0.5, 1.5)

    retry_after = headers.get("retry-after")
    if retry_after:
        try:
            return float(retry_after) + random.uniform(0.5, 1.5)
        except ValueError:
            pass

    match = re.search(
        r"try again in\s*([\d.]+)\s*(ms|s)",
        str(error),
        re.IGNORECASE,
    )
    if match:
        value = float(match.group(1))
        if match.group(2).lower() == "ms":
            value /= 1000
        return value + random.uniform(0.5, 1.5)

    return min(2 ** attempt, 30) + random.uniform(0.5, 1.5)


async def retry_async(call, attempts=8):
    for attempt in range(attempts):
        try:
            return await call()
        except Exception as error:
            if not _is_rate_limit(error) or attempt == attempts - 1:
                raise
            await asyncio.sleep(_retry_delay(error, attempt))


def retry_sync(call, attempts=8):
    for attempt in range(attempts):
        try:
            return call()
        except Exception as error:
            if not _is_rate_limit(error) or attempt == attempts - 1:
                raise
            time.sleep(_retry_delay(error, attempt))