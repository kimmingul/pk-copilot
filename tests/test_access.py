"""
Tests for pkplugin.compliance.access (≥6 tests).

Tests:
 1. Viewer can only read.
 2. Analyst can run and draft_sign.
 3. Approver can approve_sign.
 4. Admin has all permissions.
 5. AccessDeniedError raised for missing permission.
 6. Expired session is_session_valid returns False.
 7. Valid future session is_session_valid returns True.
 8. All-roles permission matrix is consistent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pkplugin.compliance.access import (
    ROLE_PERMISSIONS,
    AccessDeniedError,
    Principal,
    Role,
    check_permission,
    is_session_valid,
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_principal(role: Role, expires_future: bool = True) -> Principal:
    if expires_future:
        expiry = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        expiry = "2000-01-01T00:00:00Z"  # Past
    return Principal(
        user_id=f"{role.value}@example.com",
        role=role,
        session_token="sess_abc",
        session_expires_utc=expiry,
    )


# ---------------------------------------------------------------------------
# 1. Viewer permissions
# ---------------------------------------------------------------------------


def test_viewer_can_read() -> None:
    p = _make_principal(Role.VIEWER)
    check_permission(p, "read")  # should not raise


def test_viewer_cannot_run() -> None:
    p = _make_principal(Role.VIEWER)
    with pytest.raises(AccessDeniedError):
        check_permission(p, "run")


def test_viewer_cannot_sign() -> None:
    p = _make_principal(Role.VIEWER)
    with pytest.raises(AccessDeniedError):
        check_permission(p, "draft_sign")


# ---------------------------------------------------------------------------
# 2. Analyst permissions
# ---------------------------------------------------------------------------


def test_analyst_can_run() -> None:
    p = _make_principal(Role.ANALYST)
    check_permission(p, "run")  # should not raise


def test_analyst_can_draft_sign() -> None:
    p = _make_principal(Role.ANALYST)
    check_permission(p, "draft_sign")  # should not raise


def test_analyst_cannot_approve_sign() -> None:
    p = _make_principal(Role.ANALYST)
    with pytest.raises(AccessDeniedError):
        check_permission(p, "approve_sign")


def test_analyst_cannot_lock() -> None:
    p = _make_principal(Role.ANALYST)
    with pytest.raises(AccessDeniedError):
        check_permission(p, "lock")


# ---------------------------------------------------------------------------
# 3. Approver permissions
# ---------------------------------------------------------------------------


def test_approver_can_approve_sign() -> None:
    p = _make_principal(Role.APPROVER)
    check_permission(p, "approve_sign")  # should not raise
    check_permission(p, "review_sign")  # should not raise


def test_approver_cannot_lock() -> None:
    p = _make_principal(Role.APPROVER)
    with pytest.raises(AccessDeniedError):
        check_permission(p, "lock")


# ---------------------------------------------------------------------------
# 4. Admin has all permissions
# ---------------------------------------------------------------------------


def test_admin_has_all_permissions() -> None:
    p = _make_principal(Role.ADMIN)
    all_perms = set().union(*ROLE_PERMISSIONS.values())
    for perm in all_perms:
        check_permission(p, perm)  # should not raise


# ---------------------------------------------------------------------------
# 5. AccessDeniedError message includes role and permission
# ---------------------------------------------------------------------------


def test_access_denied_error_message() -> None:
    p = _make_principal(Role.VIEWER)
    with pytest.raises(AccessDeniedError) as exc_info:
        check_permission(p, "lock")
    msg = str(exc_info.value)
    assert "viewer" in msg.lower()
    assert "lock" in msg.lower()


# ---------------------------------------------------------------------------
# 6. Expired session is_session_valid returns False
# ---------------------------------------------------------------------------


def test_expired_session_invalid() -> None:
    p = _make_principal(Role.ANALYST, expires_future=False)
    assert not is_session_valid(p)


# ---------------------------------------------------------------------------
# 7. Valid future session
# ---------------------------------------------------------------------------


def test_valid_session() -> None:
    p = _make_principal(Role.ANALYST, expires_future=True)
    assert is_session_valid(p)


# ---------------------------------------------------------------------------
# 8. All-roles permission matrix — every role's perms is a superset of lower roles
# ---------------------------------------------------------------------------


def test_role_permission_hierarchy() -> None:
    # VIEWER ⊆ ANALYST ⊆ APPROVER ⊆ ADMIN
    roles = [Role.VIEWER, Role.ANALYST, Role.APPROVER, Role.ADMIN]
    for i in range(len(roles) - 1):
        lower = ROLE_PERMISSIONS[roles[i]]
        higher = ROLE_PERMISSIONS[roles[i + 1]]
        assert lower.issubset(higher), (
            f"{roles[i]} permissions {lower} should be subset of "
            f"{roles[i + 1]} permissions {higher}"
        )


# ---------------------------------------------------------------------------
# 9. is_session_valid with explicit 'now' parameter
# ---------------------------------------------------------------------------


def test_session_valid_with_explicit_now() -> None:
    p = Principal(
        user_id="test@example.com",
        role=Role.ANALYST,
        session_token="tok",
        session_expires_utc="2026-05-25T12:00:00Z",
    )
    past = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    future = datetime(2026, 5, 25, 14, 0, 0, tzinfo=UTC)
    assert is_session_valid(p, now=past)
    assert not is_session_valid(p, now=future)
