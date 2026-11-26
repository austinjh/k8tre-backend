"""Server-rendered portal pages for the lifecycle prototype.

These routes extend the existing Keycloak-authenticated k8tre-backend portal.
They call the internal lifecycle-core API from the server using trusted headers;
no OAuth token or shared secret is sent to the browser.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from lifecycle_client import LifecycleClient, LifecycleError
from lifecycle_roles import roles_for_user

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])
templates = Jinja2Templates(directory="templates")
CLIENT: LifecycleClient | None = None


def _client() -> LifecycleClient:
    global CLIENT
    if CLIENT is None:
        CLIENT = LifecycleClient()
    return CLIENT


def _actor(request: Request) -> tuple[str, list[str]]:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = user.get("preferred_username")
    if not username:
        raise HTTPException(status_code=401, detail="No preferred_username in session")
    return str(username), roles_for_user(user)


def _context(request: Request, **extra: Any) -> dict[str, Any]:
    username, roles = _actor(request)
    return {"username": username, "roles": roles, **extra}


def _error(request: Request, exc: LifecycleError) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "lifecycle/error.html",
        _context(request, error=exc.detail, status=exc.status_code),
        status_code=exc.status_code,
    )


def _render(request: Request, name: str, **extra: Any) -> HTMLResponse:
    return templates.TemplateResponse(request, f"lifecycle/{name}.html", _context(request, **extra))


def _as_float(form: Any, key: str, default: float = 0.0) -> float:
    try:
        return float(form.get(key, default))
    except (TypeError, ValueError):
        return default


def _as_int(form: Any, key: str, default: int = 0) -> int:
    try:
        return int(float(form.get(key, default)))
    except (TypeError, ValueError):
        return default


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _project_map(projects: list[dict[str, Any]]) -> dict[str, str]:
    return {str(project["id"]): str(project["name"]) for project in projects}


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    try:
        projects = _client().get("/v1/projects", actor=_actor(request)[0], roles=_actor(request)[1])
        summaries = [
            _client().get(
                f"/v1/projects/{project['id']}/summary",
                actor=_actor(request)[0],
                roles=_actor(request)[1],
            )
            for project in projects
        ]
    except LifecycleError as exc:
        return _error(request, exc)
    return _render(
        request,
        "index",
        projects=projects,
        summaries=summaries,
        title="Research lifecycle",
    )


@router.get("/assessments", response_class=HTMLResponse)
def assessments(request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    try:
        client = _client()
        projects = client.get("/v1/projects", actor=username, roles=roles)
        records = client.get("/v1/assessments", actor=username, roles=roles)
    except LifecycleError as exc:
        return _error(request, exc)
    names = _project_map(projects)
    return _render(
        request,
        "assessments",
        records=records,
        names=names,
        projects=projects,
    )


@router.get("/finance", response_class=HTMLResponse)
def finance(request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    try:
        client = _client()
        projects = client.get("/v1/projects", actor=username, roles=roles)
        summaries = [
            client.get(f"/v1/projects/{project['id']}/summary", actor=username, roles=roles)
            for project in projects
        ]
        quotes = client.get("/v1/quotes", actor=username, roles=roles)
        ledger = client.get("/v1/ledger-entries", actor=username, roles=roles)
        rate_card = client.get("/v1/rate-card", actor=username, roles=roles)
    except LifecycleError as exc:
        return _error(request, exc)
    names = _project_map(projects)
    return _render(
        request,
        "finance",
        projects=projects,
        summaries=summaries,
        quotes=quotes,
        ledger=ledger,
        names=names,
        rate_card=rate_card,
    )


@router.get("/allocation", response_class=HTMLResponse)
def allocation(request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    try:
        client = _client()
        projects = client.get("/v1/projects", actor=username, roles=roles)
        allocations = client.get("/v1/allocations", actor=username, roles=roles)
        capacity = client.get("/v1/capacity-snapshots", actor=username, roles=roles)
    except LifecycleError as exc:
        return _error(request, exc)
    return _render(
        request,
        "allocation",
        projects=projects,
        allocations=allocations,
        capacity=capacity,
        names=_project_map(projects),
    )


@router.get("/data-requests", response_class=HTMLResponse)
def data_requests(request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    try:
        client = _client()
        projects = client.get("/v1/projects", actor=username, roles=roles)
        records = client.get("/v1/data-requests", actor=username, roles=roles)
    except LifecycleError as exc:
        return _error(request, exc)
    return _render(
        request,
        "data-requests",
        projects=projects,
        records=records,
        names=_project_map(projects),
    )


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(project_id: str, request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    try:
        client = _client()
        summary = client.get(f"/v1/projects/{project_id}/summary", actor=username, roles=roles)
        audit = client.get(f"/v1/projects/{project_id}/audit", actor=username, roles=roles)
        evidence = client.get(f"/v1/projects/{project_id}/evidence", actor=username, roles=roles)
        data = client.get(f"/v1/projects/{project_id}/data-requests", actor=username, roles=roles)
    except LifecycleError as exc:
        return _error(request, exc)
    return _render(
        request,
        "project",
        summary=summary,
        audit=audit,
        evidence=evidence,
        data_requests=data,
    )


@router.get("/projects/{project_id}/assessment", response_class=HTMLResponse)
def assessment_form(project_id: str, request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    try:
        client = _client()
        template = client.get("/v1/assessment-template", actor=username, roles=roles)
        assessments = client.get(f"/v1/projects/{project_id}/assessments", actor=username, roles=roles)
        project = client.get(f"/v1/projects/{project_id}", actor=username, roles=roles)
    except LifecycleError as exc:
        return _error(request, exc)
    previous = assessments[-1].get("answers_json", {}) if assessments else {}
    return _render(
        request,
        "assessment-form",
        project=project,
        questions=template["questions"],
        version=template["version"],
        previous=previous,
    )


@router.post("/projects/{project_id}/assessment")
async def submit_assessment(project_id: str, request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    form = await request.form()
    try:
        client = _client()
        template = client.get("/v1/assessment-template", actor=username, roles=roles)
        allowed = {question["key"] for question in template["questions"]}
        answers = {
            key: value
            for key, value in form.multi_items()
            if key in allowed and isinstance(value, str)
        }
        client.post(
            f"/v1/projects/{project_id}/assessments",
            actor=username,
            roles=roles,
            json={"version": template["version"], "answers": answers},
        )
    except LifecycleError as exc:
        return _error(request, exc)
    return _redirect(f"/lifecycle/projects/{project_id}?saved=assessment")


@router.post("/projects")
async def create_project(request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    form = await request.form()
    try:
        client = _client()
        study_id = str(form.get("study_id", "")).strip()
        if not study_id:
            study = client.post(
                "/v1/studies",
                actor=username,
                roles=roles,
                json={
                    "title": str(form.get("study_title", "Untitled study")),
                    "description": str(form.get("study_description", "")),
                    "owner": str(form.get("owner", username)),
                },
            )
            study_id = study["id"]
        project = client.post(
            "/v1/projects",
            actor=username,
            roles=roles,
            json={
                "study_id": study_id,
                "name": str(form.get("name", "new-project")),
                "description": str(form.get("description", "")),
                "owner": str(form.get("owner", username)),
            },
        )
    except LifecycleError as exc:
        return _error(request, exc)
    return _redirect(f"/lifecycle/projects/{project['id']}?saved=project")


@router.post("/projects/{project_id}/transitions")
async def transition(project_id: str, request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    form = await request.form()
    try:
        _client().post(
            f"/v1/projects/{project_id}/transitions",
            actor=username,
            roles=roles,
            json={
                "action": str(form.get("action", "")),
                "reason": str(form.get("reason", "")) or None,
            },
        )
    except LifecycleError as exc:
        return _error(request, exc)
    return _redirect(f"/lifecycle/projects/{project_id}?saved=transition")


@router.post("/projects/{project_id}/approvals")
async def approval(project_id: str, request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    form = await request.form()
    expires = str(form.get("expires_at", "")).strip()
    try:
        _client().post(
            f"/v1/projects/{project_id}/approvals",
            actor=username,
            roles=roles,
            json={
                "kind": str(form.get("kind", "governance")),
                "decision": str(form.get("decision", "approved")),
                "decided_by": username,
                "rationale": str(form.get("rationale", "")),
                "expires_at": expires or None,
            },
        )
    except LifecycleError as exc:
        return _error(request, exc)
    return _redirect(f"/lifecycle/projects/{project_id}?saved=approval")


@router.post("/projects/{project_id}/evidence")
async def evidence(project_id: str, request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    form = await request.form()
    try:
        _client().post(
            f"/v1/projects/{project_id}/evidence",
            actor=username,
            roles=roles,
            json={
                "kind": str(form.get("kind", "")),
                "object_key": str(form.get("object_key", "")),
                "sha256": str(form.get("sha256", "")) or None,
            },
        )
    except LifecycleError as exc:
        return _error(request, exc)
    return _redirect(f"/lifecycle/projects/{project_id}?saved=evidence")


@router.post("/projects/{project_id}/quotes")
async def quote(project_id: str, request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    form = await request.form()
    resources = {
        "cpu_vcpu": _as_float(form, "cpu_vcpu"),
        "memory_gib": _as_float(form, "memory_gib"),
        "gpu_count": _as_int(form, "gpu_count"),
        "storage_gib": _as_float(form, "storage_gib"),
        "vdi_hours": _as_float(form, "vdi_hours"),
        "licences": _as_int(form, "licences"),
    }
    try:
        client = _client()
        preview = client.post(
            "/v1/quotes/estimate",
            actor=username,
            roles=roles,
            json={
                "resources": resources,
                "hours": _as_float(form, "hours", 1),
                "valid_days": _as_int(form, "valid_days", 14),
            },
        )
        quote = client.post(
            f"/v1/projects/{project_id}/quotes",
            actor=username,
            roles=roles,
            json={
                "resources": resources,
                "hours": _as_float(form, "hours", 1),
                "valid_days": _as_int(form, "valid_days", 14),
            },
        )
    except LifecycleError as exc:
        return _error(request, exc)
    return _redirect(
        f"/lifecycle/finance?quote={quote['id']}&estimated={preview['lines']['total']}"
    )


@router.post("/quotes/{quote_id}/accept")
async def accept_quote(quote_id: str, request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    form = await request.form()
    try:
        _client().post(
            f"/v1/quotes/{quote_id}/accept",
            actor=username,
            roles=roles,
            json={"rationale": str(form.get("rationale", "Accepted in portal"))},
        )
    except LifecycleError as exc:
        return _error(request, exc)
    return _redirect("/lifecycle/finance?saved=accepted-quote")


@router.post("/projects/{project_id}/budgets")
async def commit_budget(project_id: str, request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    form = await request.form()
    try:
        _client().post(
            f"/v1/projects/{project_id}/budgets",
            actor=username,
            roles=roles,
            json={
                "quote_id": str(form.get("quote_id", "")),
                "committed_amount": _as_float(form, "committed_amount"),
            },
        )
    except LifecycleError as exc:
        return _error(request, exc)
    return _redirect("/lifecycle/finance?saved=budget")


@router.post("/projects/{project_id}/simulate-usage")
async def simulate_usage(project_id: str, request: Request) -> HTMLResponse:
    """Record simulated usage and post the matching ledger charge."""
    username, roles = _actor(request)
    form = await request.form()
    try:
        client = _client()
        rates = client.get("/v1/rate-card", actor=username, roles=roles)["rates"]
        hours = _as_float(form, "hours", 1)
        cpu = _as_float(form, "cpu_vcpu")
        memory = _as_float(form, "memory_gib")
        gpu = _as_float(form, "gpu_count")
        amount = round(
            cpu * hours * rates["vcpu_hour"]
            + memory * hours * rates["gib_hour"]
            + gpu * hours * rates["gpu_hour"],
            2,
        )
        client.post(
            f"/v1/projects/{project_id}/usage-records",
            actor=username,
            roles=roles,
            json={
                "period_start": str(form.get("period_start", "")),
                "period_end": str(form.get("period_end", "")),
                "cpu_request_vcpu_hours": round(cpu * hours, 2),
                "memory_request_gib_hours": round(memory * hours, 2),
                "gpu_hours": round(gpu * hours, 2),
                "rate_card_version": "v1",
                "amount": amount,
            },
        )
        client.post(
            f"/v1/projects/{project_id}/ledger-entries",
            actor=username,
            roles=roles,
            json={
                "entry_type": "charge",
                "amount": amount,
                "reference": str(form.get("reference", "simulated-usage")),
            },
        )
    except (LifecycleError, KeyError) as exc:
        detail = exc.detail if isinstance(exc, LifecycleError) else f"Missing rate: {exc}"
        return _error(request, LifecycleError(400, detail))
    return _redirect("/lifecycle/finance?saved=usage")


@router.post("/projects/{project_id}/allocations")
async def create_allocation(project_id: str, request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    form = await request.form()
    try:
        _client().post(
            f"/v1/projects/{project_id}/allocations",
            actor=username,
            roles=roles,
            json={
                "cpu_vcpu": _as_float(form, "cpu_vcpu", 1),
                "memory_gib": _as_float(form, "memory_gib", 1),
                "gpu_count": _as_int(form, "gpu_count"),
                "storage_gib": _as_float(form, "storage_gib"),
                "rationale": str(form.get("rationale", "")),
            },
        )
    except LifecycleError as exc:
        return _error(request, exc)
    return _redirect("/lifecycle/allocation?saved=allocation")


@router.post("/projects/{project_id}/data-requests")
async def create_data_request(project_id: str, request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    form = await request.form()
    criteria = [
        value.strip()
        for value in str(form.get("criteria", "")).splitlines()
        if value.strip()
    ]
    try:
        _client().post(
            f"/v1/projects/{project_id}/data-requests",
            actor=username,
            roles=roles,
            json={
                "direction": str(form.get("direction", "ingress")),
                "dataset_name": str(form.get("dataset_name", "")),
                "classification": str(form.get("classification", "INTERNAL")),
                "owner": str(form.get("owner", username)),
                "criteria": criteria,
                "rationale": str(form.get("rationale", "")),
            },
        )
    except LifecycleError as exc:
        return _error(request, exc)
    return _redirect("/lifecycle/data-requests?saved=request")


@router.post("/data-requests/{request_id}/decision")
async def decide_data_request(request_id: str, request: Request) -> HTMLResponse:
    username, roles = _actor(request)
    form = await request.form()
    criteria = [
        value.strip()
        for value in str(form.get("criteria", "")).splitlines()
        if value.strip()
    ]
    try:
        _client().post(
            f"/v1/data-requests/{request_id}/decision",
            actor=username,
            roles=roles,
            json={
                "decision": str(form.get("decision", "approved")),
                "decided_by": username,
                "rationale": str(form.get("rationale", "")),
                "criteria": criteria,
            },
        )
    except LifecycleError as exc:
        return _error(request, exc)
    return _redirect("/lifecycle/data-requests?saved=decision")
