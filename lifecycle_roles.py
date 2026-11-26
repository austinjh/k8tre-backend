"""Map Keycloak/K8TRE identity claims to lifecycle-core roles.

The portal already receives the Keycloak userinfo object in ``session["user"]``.
No new identity provider, token exchange or browser-side role claim is needed.
Role assignments for the POC are deployment configuration, not source code, so
they can be changed without rebuilding the portal image.
"""
from __future__ import annotations

import json
import os
from typing import Any, Iterable

DEFAULT_USER_ROLES: dict[str, tuple[str, ...]] = {
    "researcher": ("researcher",),
    "project_manager": ("project_manager",),
    "dpo": ("dpo",),
    "data_owner": ("data_owner",),
    "tre_operator": ("tre_operator",),
    "finance": ("finance",),
}

ALL_ROLES = tuple(DEFAULT_USER_ROLES)


def _mapping(name: str) -> dict[str, tuple[str, ...]]:
    raw = os.environ.get(name, "{}")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for key, roles in value.items():
        if isinstance(roles, str):
            roles = [roles]
        if isinstance(roles, list):
            result[str(key).lower()] = tuple(str(role) for role in roles)
    return result


def _suffix_roles(groups: Iterable[str]) -> set[str]:
    roles: set[str] = set()
    for group in groups:
        lowered = group.lower()
        if lowered.endswith("-admin"):
            roles.add("project_manager")
        if lowered.endswith("-analyst") or lowered.endswith("-researcher"):
            roles.add("researcher")
    return roles


def roles_for_user(user: dict[str, Any]) -> list[str]:
    """Return lifecycle roles for an authenticated Keycloak userinfo object."""
    username = str(user.get("preferred_username", "")).lower()
    groups = [str(group) for group in (user.get("groups") or [])]

    roles = _suffix_roles(groups)
    group_roles = _mapping("LIFECYCLE_ROLE_GROUPS_JSON")
    user_roles = _mapping("LIFECYCLE_ROLE_USERS_JSON")
    for group in groups:
        roles.update(group_roles.get(group.lower(), ()))
    roles.update(user_roles.get(username, ()))
    return sorted(role for role in roles if role in ALL_ROLES)
