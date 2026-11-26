"""Server-side httpx client for lifecycle-core.

Browser JavaScript never calls lifecycle-core and never sees the shared token.
The FastAPI portal validates the Keycloak session first, then sends trusted
actor headers to the internal service.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

import httpx

DEFAULT_BASE_URL = "http://lifecycle-core.lifecycle.svc.cluster.local:8000"


class LifecycleError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class LifecycleClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("LIFECYCLE_CORE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.token = token if token is not None else os.environ.get("LIFECYCLE_INTERNAL_TOKEN", "")
        self._client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=False)

    def request(
        self,
        method: str,
        path: str,
        *,
        actor: str,
        roles: list[str] | tuple[str, ...] = (),
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        headers = {
            "x-lifecycle-actor": actor,
            "x-lifecycle-roles": ",".join(roles),
            "accept": "application/json",
        }
        if self.token:
            headers["x-lifecycle-token"] = self.token
        try:
            response = self._client.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                json=dict(json) if json is not None else None,
                params=dict(params) if params else None,
            )
        except httpx.HTTPError as exc:
            raise LifecycleError(503, f"lifecycle-core is unavailable: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise LifecycleError(response.status_code, str(detail))

        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise LifecycleError(502, "lifecycle-core returned a non-JSON response") from exc

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)
