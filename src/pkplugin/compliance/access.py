"""
RBAC role enforcement for pk-copilot v2.0.

Implements §11.10(d) (access restriction) and §11.10(g) (authority checks).

Usage::

    principal = Principal(
        user_id="analyst@example.com",
        role=Role.ANALYST,
        session_token="sess_abc123",
        session_expires_utc="2026-05-25T11:00:00Z",
    )
    check_permission(principal, "run")   # raises AccessDeniedError if not allowed
    check_permission(principal, "approve_sign")  # raises — analyst cannot approve
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role(str, Enum):
    """RBAC roles — ordered from least to most privileged."""

    VIEWER = "viewer"
    ANALYST = "analyst"
    APPROVER = "approver"
    ADMIN = "admin"


# ---------------------------------------------------------------------------
# Permission matrix
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.VIEWER: {"read"},
    Role.ANALYST: {"read", "run", "draft_sign"},
    Role.APPROVER: {"read", "run", "draft_sign", "review_sign", "approve_sign"},
    Role.ADMIN: {
        "read",
        "run",
        "draft_sign",
        "review_sign",
        "approve_sign",
        "lock",
        "unlock_with_signed_reason",
    },
}


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """An authenticated user with a current session."""

    user_id: str
    role: Role
    session_token: str
    """Short-lived session identifier."""
    session_expires_utc: str
    """ISO 8601 UTC expiry timestamp, e.g. '2026-05-25T11:00:00Z'."""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AccessDeniedError(Exception):
    """Raised when a principal lacks the required permission."""


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------


def check_permission(principal: Principal, required: str) -> None:
    """Assert *principal* has *required* permission and that their session has not expired.

    Raises:
        AccessDeniedError: if the principal's role does not include *required*,
            or if the session has expired.
    """
    # MINOR-4: Reject expired sessions before checking role permissions
    if not is_session_valid(principal):
        raise AccessDeniedError(
            f"User {principal.user_id!r} session has expired"
        )

    allowed = ROLE_PERMISSIONS.get(principal.role, set())
    if required not in allowed:
        raise AccessDeniedError(
            f"User {principal.user_id!r} with role {principal.role.value!r} "
            f"does not have permission {required!r}. "
            f"Allowed: {sorted(allowed)}"
        )


def is_session_valid(principal: Principal, now: datetime | None = None) -> bool:
    """Return True if the principal's session has not expired.

    Args:
        principal: The principal to check.
        now: Current UTC time; defaults to ``datetime.now(timezone.utc)``.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        # Parse ISO 8601 — handle both Z suffix and +00:00
        expiry_str = principal.session_expires_utc.replace("Z", "+00:00")
        expiry = datetime.fromisoformat(expiry_str)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return now < expiry
    except ValueError:
        return False
