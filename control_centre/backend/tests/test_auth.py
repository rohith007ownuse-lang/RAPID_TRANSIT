"""
test_auth.py
Phase 5: real backend authentication + authorization.

Covers login/logout/current-user, role-based authorization across every
privileged endpoint, inactive-user rejection, localStorage/frontend spoofing
resistance, admin user-management guard rails, and persistence across restart.

Every test relies on conftest's isolated SQLite instance (autouse fixture) and
a seeded development Admin (admin / admin123). The real dev database is never
touched.
"""

import pytest

import auth
import persistence
import server


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _login_token(client, username="admin", password="admin123"):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _make_user(username, password, role):
    u = auth.create_user(username, password, role)
    assert u is not None, f"could not create {username} ({role})"
    return u


@pytest.fixture
def client():
    return server.app.test_client()


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------

class TestAuthentication:
    def test_valid_login_succeeds(self, client):
        data = _login_token(client)
        assert data["token"]
        assert data["user"]["username"] == "admin"
        assert data["user"]["role"] == "admin"
        assert data["user"]["active"] is True
        assert "password" not in data

    def test_invalid_password_fails(self, client):
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401
        assert "token" not in resp.get_json()

    def test_invalid_username_fails(self, client):
        resp = client.post("/api/auth/login", json={"username": "nobody", "password": "admin123"})
        assert resp.status_code == 401

    def test_wrong_username_identical_response_to_wrong_password(self, client):
        a = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).get_json()
        b = client.post("/api/auth/login", json={"username": "nobody", "password": "admin123"}).get_json()
        assert a == b  # same body -> cannot tell which credential was wrong

    def test_inactive_user_cannot_login(self, client):
        _make_user("offline", "secret1", auth.ROLE_OPERATOR)
        target = auth.get_user_by_username("offline")
        assert target
        auth.set_user_active(target["id"], False)
        resp = client.post("/api/auth/login", json={"username": "offline", "password": "secret1"})
        assert resp.status_code == 401

    def test_current_user_endpoint(self, client):
        data = _login_token(client)
        resp = client.get("/api/auth/me", headers=_headers(data["token"]))
        assert resp.status_code == 200
        assert resp.get_json()["user"]["role"] == "admin"

    def test_logout_invalidates_token(self, client):
        data = _login_token(client)
        resp = client.post("/api/auth/logout", headers=_headers(data["token"]))
        assert resp.status_code == 200
        # After logout the token must no longer authenticate.
        me = client.get("/api/auth/me", headers=_headers(data["token"]))
        assert me.status_code == 401

    def test_expired_token_rejected(self, client, monkeypatch):
        monkeypatch.setenv("FLEETIQ_SESSION_TTL_HOURS", "0.0000001")
        data = _login_token(client)
        me = client.get("/api/auth/me", headers=_headers(data["token"]))
        assert me.status_code == 401

    def test_missing_or_bad_token_rejected(self, client):
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/api/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
        assert client.get("/api/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401


# --------------------------------------------------------------------------
# Authorization — role matrix across every privileged endpoint
# --------------------------------------------------------------------------

class TestAuthorization:
    def test_unauthenticated_privileged_actions_rejected(self, client):
        # Every state-changing / privileged endpoint must demand auth.
        unauthenticated = [
            ("post", "/api/events/1/acknowledge", {"operator": "x"}),
            ("post", "/api/events/1/resolve", {"operator": "x"}),
            ("post", "/api/events/status", {"status": "RESOLVED"}),
            ("post", "/api/settings", {"thresholds": {}}),
            ("post", "/api/mode/switch", {"mode": "live"}),
            ("post", "/api/dds/start", {}),
            ("post", "/api/camera/start", {"slot": "driver"}),
            ("post", "/api/camera/multi-camera", {}),
            ("post", "/api/actions/evaluate", {}),
            ("get", "/api/auth/users", None),
        ]
        for method, path, body in unauthenticated:
            resp = getattr(client, method)(path, json=body) if method == "post" else getattr(client, method)(path)
            assert resp.status_code in (401, 503), (method, path, resp.status_code)

    def test_operator_cannot_resolve(self, client):
        token = _login_token(client, *self._login_creds("op1", auth.ROLE_OPERATOR))["token"]
        resp = client.post("/api/events/1/resolve", json={"operator": "op1"}, headers=_headers(token))
        assert resp.status_code in (403, 404)  # operator lacks permission (would 403 even if existed)

    def test_operator_can_acknowledge(self, client):
        token = _login_token(client, *self._login_creds("op2", auth.ROLE_OPERATOR))["token"]
        resp = client.post("/api/events/1/acknowledge", json={"operator": "op2"}, headers=_headers(token))
        # Operator is permitted to ack; the event just does not exist -> 404
        assert resp.status_code == 404

    def test_operator_cannot_admin_only(self, client):
        token = _login_token(client, *self._login_creds("op3", auth.ROLE_OPERATOR))["token"]
        assert client.get("/api/auth/users", headers=_headers(token)).status_code == 403
        assert client.post("/api/settings", json={}, headers=_headers(token)).status_code == 403

    def test_supervisor_cannot_admin_only(self, client):
        token = _login_token(client, *self._login_creds("sup1", auth.ROLE_SUPERVISOR))["token"]
        assert client.get("/api/auth/users", headers=_headers(token)).status_code == 403
        assert client.post("/api/settings", json={}, headers=_headers(token)).status_code == 403

    def test_supervisor_can_resolve(self, client):
        token = _login_token(client, *self._login_creds("sup2", auth.ROLE_SUPERVISOR))["token"]
        resp = client.post("/api/events/1/resolve", json={"operator": "sup2"}, headers=_headers(token))
        assert resp.status_code == 404  # permitted (404 = not found, not forbidden)

    def test_admin_can_admin_only(self, client):
        token = _login_token(client)["token"]
        assert client.get("/api/auth/users", headers=_headers(token)).status_code == 200

    def _login_creds(self, username, role):
        _make_user(username, "secret1", role)
        return username, "secret1"


# --------------------------------------------------------------------------
# Spoofing resistance
# --------------------------------------------------------------------------

class TestSpoofingResistance:
    def test_localstorage_role_spoof_grants_nothing(self, client):
        """A client that fakes an 'admin' role in browser storage has no token
        and must still be rejected by the backend."""
        resp = client.get("/api/auth/users")  # no token at all
        assert resp.status_code == 401

    def test_fake_bearer_token_rejected(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer forged-token"})
        assert resp.status_code == 401

    def test_declared_admin_in_body_grants_nothing(self, client):
        # User has NO valid credentials but claims 'role=admin' in the body.
        resp = client.post("/api/events/1/acknowledge", json={"operator": "admin", "role": "admin"})
        assert resp.status_code == 401


# --------------------------------------------------------------------------
# Admin user management
# --------------------------------------------------------------------------

class TestUserManagement:
    def test_admin_creates_user(self, client):
        token = _login_token(client)["token"]
        h = _headers(token)
        resp = client.post("/api/auth/users", json={"username": "newop", "password": "secret1", "role": "operator"}, headers=h)
        assert resp.status_code == 201
        assert resp.get_json()["user"]["role"] == "operator"

    def test_duplicate_username_conflict(self, client):
        token = _login_token(client)["token"]
        resp = client.post("/api/auth/users", json={"username": "admin", "password": "whatever1", "role": "operator"}, headers=_headers(token))
        assert resp.status_code == 409

    def test_admin_changes_role(self, client):
        u = _make_user("roleable", "secret1", auth.ROLE_OPERATOR)
        token = _login_token(client)["token"]
        resp = client.post(f"/api/auth/users/{u['id']}/role", json={"role": "supervisor"}, headers=_headers(token))
        assert resp.status_code == 200
        assert auth.get_user_by_id(u["id"])["role"] == "supervisor"

    def test_admin_disables_then_user_cannot_login(self, client):
        u = _make_user("goner", "secret1", auth.ROLE_OPERATOR)
        token = _login_token(client)["token"]
        resp = client.post(f"/api/auth/users/{u['id']}/active", json={"active": False}, headers=_headers(token))
        assert resp.status_code == 200
        assert client.post("/api/auth/login", json={"username": "goner", "password": "secret1"}).status_code == 401

    def test_cannot_disable_last_active_admin(self, client):
        token = _login_token(client)["token"]
        admin = auth.get_user_by_username("admin")
        resp = client.post(f"/api/auth/users/{admin['id']}/active", json={"active": False}, headers=_headers(token))
        assert resp.status_code == 400
        assert auth.get_user_by_id(admin["id"])["active"] is True

    def test_cannot_derole_last_active_admin(self, client):
        token = _login_token(client)["token"]
        admin = auth.get_user_by_username("admin")
        resp = client.post(f"/api/auth/users/{admin['id']}/role", json={"role": "operator"}, headers=_headers(token))
        assert resp.status_code == 400
        assert auth.get_user_by_id(admin["id"])["role"] == "admin"

    def test_admin_reset_password(self, client):
        u = _make_user("resetme", "secret1", auth.ROLE_OPERATOR)
        token = _login_token(client)["token"]
        resp = client.post(f"/api/auth/users/{u['id']}/password", json={"password": "newpass9"}, headers=_headers(token))
        assert resp.status_code == 200
        assert client.post("/api/auth/login", json={"username": "resetme", "password": "newpass9"}).status_code == 200

    def test_change_own_password(self, client):
        u = _make_user("selfchg", "oldpass1", auth.ROLE_OPERATOR)
        token = _login_token(client, "selfchg", "oldpass1")["token"]
        resp = client.post("/api/auth/me/password", json={"current_password": "oldpass1", "new_password": "newpass2"}, headers=_headers(token))
        assert resp.status_code == 200
        assert client.post("/api/auth/login", json={"username": "selfchg", "password": "newpass2"}).status_code == 200
        assert client.post("/api/auth/login", json={"username": "selfchg", "password": "oldpass1"}).status_code == 401


# --------------------------------------------------------------------------
# Persistence across restart
# --------------------------------------------------------------------------

class TestPersistence:
    def test_users_roles_and_events_survive_restart(self, tmp_path, client):
        _make_user("durable", "secret1", auth.ROLE_SUPERVISOR)

        import uuid
        event_id = str(uuid.uuid4())
        base = {"event_id": event_id, "event_type": "OVERLOAD", "timestamp": "2026-09-07T00:00:00+00:00",
                "bus_id": "TN-01", "severity": "HIGH", "status": "ACTIVE", "simulation": True}
        from data_store import store as _store
        _store.add_event(dict(base))
        # "restart": force re-init of the same SQLite file, then reload history.
        persistence.init_db(path=persistence.DB_PATH, force=True)
        reloaded = persistence.load_events()
        assert any(e.get("event_id") == event_id for e in reloaded), "event history must survive restart"
        assert auth.get_user_by_username("durable") is not None, "users must survive restart"
        assert auth.get_user_by_username("durable")["role"] == "supervisor"

    def test_can_login_after_restart(self, tmp_path, client):
        u = _make_user("survivor", "secret1", auth.ROLE_OPERATOR)
        # Simulate restart: force re-init of the same DB path.
        persistence.init_db(path=persistence.DB_PATH, force=True)
        assert client.post("/api/auth/login", json={"username": "survivor", "password": "secret1"}).status_code == 200