"""Tests for the server-rendered lifecycle portal extension."""
from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

import lifecycle_roles
import lifecycle_routes
from lifecycle_client import LifecycleClient

USER = {
    "preferred_username": "alice",
    "groups": ["asthma-analyst", "asthma-admin"],
}


@pytest.fixture()
def portal(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fake = FakeClient()
    monkeypatch.setattr(lifecycle_routes, "CLIENT", fake)

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-session-secret")
    app.include_router(lifecycle_routes.router)

    @app.get("/_login")
    def login(request: Request) -> dict[str, str]:
        request.session["user"] = dict(USER)
        return {"status": "ok"}

    client = TestClient(app)
    client.get("/_login")
    client.fake = fake  # type: ignore[attr-defined]
    return client


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.responses: dict[str, Any] = {}
        self.fail: dict[str, lifecycle_routes.LifecycleError] = {}

    def get(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("GET", path, kwargs))
        if path in self.fail:
            raise self.fail[path]
        return self.responses.get(path, [])

    def post(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("POST", path, kwargs))
        if path in self.fail:
            raise self.fail[path]
        return self.responses.get(path, {"id": "new-id"})


def test_roles_from_groups_and_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIFECYCLE_ROLE_USERS_JSON", '{"alice": ["dpo", "finance"]}')
    assert lifecycle_roles.roles_for_user(USER) == [
        "dpo",
        "finance",
        "project_manager",
        "researcher",
    ]


def test_client_sends_trusted_headers_without_browser_exposure() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update({key: request.headers[key] for key in request.headers if key.startswith("x-lifecycle")})
        return httpx.Response(200, json={"status": "ok"})

    client = LifecycleClient(
        base_url="http://lifecycle-core.lifecycle",
        token="do-not-show-this-token",
        transport=httpx.MockTransport(handler),
    )
    result = client.get("/healthz", actor="alice", roles=["researcher"])
    assert result == {"status": "ok"}
    assert seen["x-lifecycle-actor"] == "alice"
    assert seen["x-lifecycle-roles"] == "researcher"
    assert seen["x-lifecycle-token"] == "do-not-show-this-token"
    # The token is only present on the server-to-server request, never in the
    # response body that could reach a browser.
    assert "do-not-show-this-token" not in str(result)


def test_dashboard_renders_projects_and_roles(portal: TestClient) -> None:
    fake: FakeClient = portal.fake  # type: ignore[assignment]
    fake.responses["/v1/projects"] = [
        {
            "id": "p1",
            "name": "asthma-demo",
            "description": "Demonstration project",
            "state": "DRAFT",
            "control_tier": None,
        }
    ]
    fake.responses["/v1/projects/p1/summary"] = {
        "project": fake.responses["/v1/projects"][0],
        "consumed_amount": 0.0,
        "utilisation": 0.0,
        "alert": "OK",
        "budget": None,
    }

    response = portal.get("/lifecycle")
    assert response.status_code == 200
    assert "asthma-demo" in response.text
    assert "researcher" in response.text
    assert ("GET", "/v1/projects", {"actor": "alice", "roles": ["project_manager", "researcher"]}) in fake.calls


def test_assessment_form_submits_answers_only(portal: TestClient) -> None:
    fake: FakeClient = portal.fake  # type: ignore[assignment]
    fake.responses["/v1/assessment-template"] = {
        "version": "2026-11-v1",
        "questions": [
            {
                "key": "data_category",
                "prompt": "Sensitivity?",
                "type": "single",
                "options": ["ANONYMISED", "PERSONAL"],
            }
        ],
    }
    fake.responses["/v1/projects/p1"] = {"id": "p1", "name": "asthma-demo"}

    form = portal.get("/lifecycle/projects/p1/assessment")
    assert form.status_code == 200
    assert "Sensitivity?" in form.text

    submitted = portal.post(
        "/lifecycle/projects/p1/assessment",
        data={
            "version": "2026-11-v1",
            "data_category": "PERSONAL",
            "risk_score": "0",
            "classification": "PUBLIC",
        },
        follow_redirects=False,
    )
    assert submitted.status_code == 303
    assessment_call = [
        call
        for call in fake.calls
        if call[0] == "POST" and call[1] == "/v1/projects/p1/assessments"
    ][0]
    payload = assessment_call[2]["json"]
    assert payload["answers"] == {"data_category": "PERSONAL"}
    assert "risk_score" not in payload
    assert "classification" not in payload


def test_transition_error_is_rendered_as_html(portal: TestClient) -> None:
    fake: FakeClient = portal.fake  # type: ignore[assignment]
    fake.fail["/v1/projects/p1/transitions"] = lifecycle_routes.LifecycleError(
        403, "Action submit requires one of roles"
    )
    response = portal.post(
        "/lifecycle/projects/p1/transitions",
        data={"action": "submit", "reason": ""},
    )
    assert response.status_code == 403
    assert "Action submit requires one of roles" in response.text
