"""EDGAR HTTP client with token-bucket rate limiting and retry logic."""

import time

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception


class _RateLimiter:
    """Simple token-bucket rate limiter."""

    def __init__(self, requests_per_second: float):
        self._min_interval = 1.0 / requests_per_second
        self._last_call = 0.0

    def wait(self):
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, requests.HTTPError):
        return exc.response is not None and exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, (requests.ConnectionError, requests.Timeout))


class EdgarClient:
    def __init__(self, config: dict):
        edgar_cfg = config["edgar"]
        rl_cfg = edgar_cfg.get("rate_limit", {})

        self._session = requests.Session()
        self._session.headers.update(edgar_cfg.get("headers", {}))
        self._limiter = _RateLimiter(rl_cfg.get("requests_per_second", 10))

    def fetch(self, url: str) -> dict:
        self._limiter.wait()
        return self._fetch_with_retry(url)

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _fetch_with_retry(self, url: str) -> dict:
        response = self._session.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
