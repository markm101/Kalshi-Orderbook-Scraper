from __future__ import annotations

import random
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives.asymmetric import rsa

from kalshi_capture.auth import auth_headers


class KalshiClient:
    def __init__(
        self,
        base_url: str,
        key_id: str,
        private_key: rsa.RSAPrivateKey,
        timeout: float = 20.0,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.key_id = key_id
        self.private_key = private_key
        self.max_retries = max_retries
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> KalshiClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.request("GET", path, params=params)

    def request(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/"):
            path = f"/{path}"

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            request = self._client.build_request(method, path, params=params)
            sign_path = urlparse(str(request.url)).path
            request.headers.update(auth_headers(self.private_key, self.key_id, method, sign_path))

            try:
                response = self._client.send(request)
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    if attempt < self.max_retries:
                        self._sleep_before_retry(attempt)
                        continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Expected JSON object response")
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                raise

        raise RuntimeError("Request failed") from last_error

    @staticmethod
    def _sleep_before_retry(attempt: int) -> None:
        base = min(8.0, 0.5 * (2**attempt))
        time.sleep(base + random.uniform(0.0, base * 0.25))
