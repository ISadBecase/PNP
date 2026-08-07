import logging

from openai import RateLimitError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_random_exponential

logger = logging.getLogger(__name__)

# OPENAI API rate limit error code: 429;CAMEL对返回异常进行了重包装
# 相关解决方案：https://developers.openai.com/cookbook/examples/how_to_handle_rate_limits#example-parallel-processing-script
def _is_rate_limit(error):
    message = str(error).lower()
    if "insufficient_quota" in message:
        return False

    response = getattr(error, "response", None)
    wrapped_rate_limit = "error code: 429" in message or "rate_limit_exceeded" in message
    if not isinstance(error, RateLimitError) and getattr(response, "status_code", None) != 429 and not wrapped_rate_limit:
        return False

    code = getattr(error, "code", "")
    body = getattr(error, "body", {}) or {}
    if isinstance(body, dict):
        code = code or body.get("code") or body.get("error", {}).get("code", "")

    return code != "insufficient_quota"


def _log_retry(retry_state):
    error = retry_state.outcome.exception()
    wait = retry_state.next_action.sleep
    logger.warning(
        "Rate limit: %s; retry %d/%d in %.2f seconds",
        type(error).__name__,
        retry_state.attempt_number + 1,
        retry_state.retry_object.stop.max_attempt_number,
        wait,
    )


def _retry(attempts):
    return retry(
        retry=retry_if_exception(_is_rate_limit),
        wait=wait_random_exponential(multiplier=2, min=1, max=60),
        stop=stop_after_attempt(attempts),
        before_sleep=_log_retry,
        reraise=True,
    )


async def retry_async(call, attempts=6):
    @_retry(attempts)
    async def run():
        return await call()

    return await run()


def retry_sync(call, attempts=6):
    @_retry(attempts)
    def run():
        return call()

    return run()
