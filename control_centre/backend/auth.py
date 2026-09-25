"""
auth.py
Real backend authentication + authorization for FLEET-IQ.

Security model
--------------
- Users + sessions live in the SAME SQLite database as the event log
  (stdlib sqlite3 only; no external identity providers or services).
- Passwords are hashed with hashlib.pbkdf2_hmac (SHA-256, 260 000
  iterations, per-user random salt). Plaintext is never stored or logged.
  The stored format is:  pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>
- Sessions are opaque bearer tokens (secrets.token_urlsafe) stored
  server-side with an expiry timestamp. Every privileged request is
  re-validated against the sessions table: token + expiry + user active.
- Roles (operator < supervisor < admin) are enforced on the BACKEND for
  every privileged endpoint. Frontend role display is cosmetic only.

Development bootstrap
---------------------
ensure_bootstrap_admin() creates the initial Admin on first startup ONLY
if no user named FLEETIQ_ADMIN_USER exists:
  * username: FLEETIQ_ADMIN_USER  (default "admin")
  * password: FLEETIQ_ADMIN_PASSWORD (default "admin123" - DEVELOPMENT
    ONLY; the server prints a warning telling operators to change it).
Never print real passwords into logs.
"""

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timezone

import persistence

ROLE_OPERATOR = "operator"
ROLE_SUPERVISOR = "supervisor"
ROLE_ADMIN = "admin"
ROLES = (ROLE_OPERATOR, ROLE_SUPERVISOR, ROLE_ADMIN)

_PBKDF2_ITERATIONS = 260_000
_SALT_BYTES = 16
_TOKEN_BYTES = 32
_DEFAULT_SESSION_TTL_HOURS = 12.0


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _hash_password(password: str, salt: bytes | None = None) -> str:
    """Return pbkdf2-hmac(SHA-256) password hash in a versioned format."""
    salt = salt or secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        _b64(salt),
        _b64(digest),
    )


def _b64(raw: bytes) -> str:
    import base64
    return base64.b64encode(raw).decode("ascii")


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification of a stored pbkdf2 hash."""
    try:
        _alg, iters, salt_b64, hash_b64 = stored.split("$")
        if _alg != "pbkdf2_sha256":
            return False
        import base64
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iters))
    return hmac.compare_digest(digest, expected)


def _session_ttl_hours() -> float:
    try:
        return float(os.environ.get("FLEETIQ_SESSION_TTL_HOURS", _DEFAULT_SESSION_TTL_HOURS))
    except (TypeError, ValueError):
        return _DEFAULT_SESSION_TTL_HOURS


# ---------------------------------------------------------------------------
# User records (row helpers)
# ---------------------------------------------------------------------------

def _row_to_user(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_user_by_id(user_id: int) -> dict | None:
    conn = persistence._conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row)
    finally:
        conn.close()


def get_user_by_username(username: str) -> dict | None:
    conn = persistence._conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return _row_to_user(row)
    finally:
        conn.close()


def _user_hash(username: str) -> str | None:
    """Return only the password_hash row (never exposed over the API)."""
    conn = persistence._conn()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        return row["password_hash"] if row else None
    finally:
        conn.close()


def list_users() -> list[dict]:
    conn = persistence._conn()
    try:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY username COLLATE NOCASE ASC"
        ).fetchall()
        return [_row_to_user(r) for r in rows]
    finally:
        conn.close()


def _active_admin_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND active = 1"
    ).fetchone()["c"]


def _is_last_active_admin(user_id: int) -> bool:
    conn = persistence._conn()
    try:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None or user["role"] != "admin" or not user["active"]:
            return False
        return _active_admin_count(conn) <= 1
    finally:
        conn.close()


def create_user(username: str, password: str, role: str) -> dict | None:
    """Create a user. Returns the public record, or None if the username is
    taken or the role is invalid. Raises nothing."""
    username = (username or "").strip()
    if not username or role not in ROLES or not password:
        return None
    if get_user_by_username(username) is not None:
        return None
    now = _now_iso()
    conn = persistence._conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, active, created_at, updated_at)"
            " VALUES (?, ?, ?, 1, ?, ?)",
            (username, _hash_password(password), role, now, now),
        )
        conn.commit()
        return get_user_by_id(cur.lastrowid)
    except Exception:
        return None
    finally:
        conn.close()


def update_user_role(user_id: int, role: str) -> tuple[bool, str]:
    """Change a user's role. Refuses to de-role the last active admin."""
    if role not in ROLES:
        return False, "invalid role"
    if _is_last_active_admin(user_id) and role != ROLE_ADMIN:
        return False, "cannot change role of the last active admin"
    conn = persistence._conn()
    try:
        conn.execute(
            "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
            (role, _now_iso(), user_id),
        )
        conn.commit()
        return True, "ok"
    finally:
        conn.close()


def set_user_active(user_id: int, active: bool) -> tuple[bool, str]:
    """Enable/disable a user. Refuses to disable the last active admin."""
    if _is_last_active_admin(user_id) and not active:
        return False, "cannot disable the last active admin"
    conn = persistence._conn()
    try:
        conn.execute(
            "UPDATE users SET active = ?, updated_at = ? WHERE id = ?",
            (1 if active else 0, _now_iso(), user_id),
        )
        conn.commit()
        return True, "ok"
    finally:
        conn.close()


def update_password(user_id: int, new_password: str) -> bool:
    if not new_password:
        return False
    conn = persistence._conn()
    try:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (_hash_password(new_password), _now_iso(), user_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sessions (server-side bearer tokens)
# ---------------------------------------------------------------------------

def create_session(user_id: int) -> tuple[str, float]:
    """Issue an opaque bearer token for a user. Returns (token, expires_at)."""
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    expires_at = time.time() + _session_ttl_hours() * 3600.0
    conn = persistence._conn()
    try:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (token, user_id, _now_iso(), expires_at),
        )
        conn.commit()
    finally:
        conn.close()
    return token, expires_at


def get_user_by_token(token: str) -> dict | None:
    """Resolve a bearer token to an ACTIVE user, else None (and drop invalid
    or expired tokens so the sessions table does not grow unbounded)."""
    if not token:
        return None
    conn = persistence._conn()
    try:
        row = conn.execute(
            "SELECT user_id, expires_at FROM sessions WHERE token = ?", (token,)
        ).fetchone()
        if row is None:
            return None
        if time.time() > row["expires_at"]:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        user = get_user_by_id(row["user_id"])
        if user is None or not user["active"]:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        return user
    finally:
        conn.close()


def revoke_session(token: str) -> None:
    if not token:
        return
    conn = persistence._conn()
    try:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def token_from_request(req) -> str | None:
    """Extract the bearer token from an HTTP request (Authorization header
    preferred, query/body fallback kept for buses/cameras in the local SPA)."""
    auth = req.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip() or None
    token = req.args.get("token")
    if token:
        return token
    try:
        body = req.get_json(silent=True) or {}
    except Exception:
        body = {}
    return body.get("token") or None


def require_auth(req):
    """Return the authenticated active user for a request, or None."""
    return get_user_by_token(token_from_request(req))


def authenticate(username: str, password: str) -> dict | None:
    """Verify credentials. Returns the public user record (active only) or
    None. The same None is returned for unknown username, wrong password,
    and inactive account so the API never reveals which was wrong."""
    if not username or not password:
        return None
    user = get_user_by_username(username)
    if user is None or not user["active"]:
        return None
    stored_hash = _user_hash(username)
    if stored_hash is None or not verify_password(password, stored_hash):
        return None
    return user


# ---------------------------------------------------------------------------
# Development bootstrap
# ---------------------------------------------------------------------------

def ensure_bootstrap_admin():
    """Create the initial Admin account on first startup (idempotent).

    DEVELOPMENT ONLY: the default password is "admin123" and is overridable
    at startup with FLEETIQ_ADMIN_PASSWORD. The password itself is never
    written to logs.
    """
    username = os.environ.get("FLEETIQ_ADMIN_USER", "admin").strip() or "admin"
    existing = get_user_by_username(username)
    if existing is not None:
        return existing
    password = os.environ.get("FLEETIQ_ADMIN_PASSWORD", "admin123")
    user = create_user(username, password, ROLE_ADMIN)
    if user is None:
        return None
    using_default = "FLEETIQ_ADMIN_PASSWORD" not in os.environ
    if using_default:
        print(
            f"[control-centre] Created DEVELOPMENT admin user '{username}' with the "
            "default password. Set FLEETIQ_ADMIN_PASSWORD (and FLEETIQ_ADMIN_USER) "
            "before deploying and change it immediately."
        )
    else:
        print(f"[control-centre] Created initial admin user '{username}' (password from FLEETIQ_ADMIN_PASSWORD).")
    return user


def user_payload(user: dict) -> dict:
    """Public user representation returned by the API (never a hash)."""
    if user is None:
        return {}
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "active": user["active"],
        "created_at": user["created_at"],
        "updated_at": user["updated_at"],
    }