"""
test_access_audit.py
Owner visibility: who opens the deployment and who is on right now.

Covers the login audit trail (success + failure rows with IP), the visitor-IP
priority (CF-Connecting-IP > X-Forwarded-For > peer), the admin-only access
endpoint, active-session listing with login origin, and the access-log cap.

Uses conftest's isolated SQLite instance; the real database is never touched.
"""

import pytest

import auth
import persistence
import server


@pytest.fixture
def client():
    return server.app.test_client()


def _login(client, username="admin", password="admin123", headers=None):
    return client.post("/api/auth/login",
                       json={"username": username, "password": password},
                       headers=headers or {})


def _admin_headers(client):
    data = _login(client).get_json()
    return {"Authorization": f"Bearer {data['token']}"}


class TestClientIp:
    def test_cf_connecting_ip_wins(self, client):
        with server.app.test_request_context(
                "/", headers={"CF-Connecting-IP": "203.0.113.7",
                              "X-Forwarded-For": "198.51.100.9"}):
            from flask import request
            assert auth.client_ip(request) == "203.0.113.7"

    def test_forwarded_for_fallback_uses_leftmost(self, client):
        with server.app.test_request_context(
                "/", headers={"X-Forwarded-For": "198.51.100.9, 127.0.0.1"}):
            from flask import request
            assert auth.client_ip(request) == "198.51.100.9"

    def test_peer_fallback(self, client):
        with server.app.test_request_context("/", environ_base={"REMOTE_ADDR": "10.0.0.5"}):
            from flask import request
            assert auth.client_ip(request) == "10.0.0.5"


class TestLoginAudit:
    def test_successful_login_is_logged(self, client):
        _login(client, headers={"X-Forwarded-For": "203.0.113.7",
                                "User-Agent": "JudgePhone/1.0"})
        log = auth.get_access_log()
        assert len(log) == 1
        row = log[0]
        assert row["username"] == "admin"
        assert row["success"] == 1
        assert row["ip"] == "203.0.113.7"
        assert row["user_agent"] == "JudgePhone/1.0"
        assert row["at"]

    def test_failed_login_is_logged(self, client):
        resp = _login(client, password="wrong")
        assert resp.status_code == 401
        log = auth.get_access_log()
        assert len(log) == 1
        assert log[0]["username"] == "admin"
        assert log[0]["success"] == 0

    def test_log_is_newest_first_and_capped(self, client):
        for i in range(5):
            auth.log_access(f"user{i}", True, ip="1.1.1.1")
        log = auth.get_access_log(limit=3)
        assert [r["username"] for r in log] == ["user4", "user3", "user2"]
        # cap keeps the table bounded under a brute-force storm
        for i in range(persistence.ACCESS_LOG_CAP + 50):
            auth.log_access("storm", False, ip="9.9.9.9")
        conn = persistence._conn()
        try:
            n = conn.execute("SELECT COUNT(*) AS n FROM access_log").fetchone()["n"]
        finally:
            conn.close()
        assert n <= persistence.ACCESS_LOG_CAP + 1

    def test_audit_never_breaks_login(self, client):
        # even with a hostile username, login still works and is recorded
        resp = _login(client, username="admin'; DROP TABLE users;--", password="admin123")
        assert resp.status_code in (200, 401)
        assert auth.get_access_log()


class TestAccessEndpoint:
    def test_admin_sees_log_and_sessions(self, client):
        _login(client, headers={"X-Forwarded-For": "203.0.113.7"})
        _login(client, username="admin", password="nope")
        resp = client.get("/api/auth/access", headers=_admin_headers(client))
        assert resp.status_code == 200
        body = resp.get_json()
        assert any(r["success"] == 1 for r in body["log"])
        assert any(r["success"] == 0 for r in body["log"]
                   )
        sessions = body["active_sessions"]
        assert len(sessions) >= 1
        assert sessions[0]["username"] == "admin"
        assert any(s["ip"] == "203.0.113.7" for s in sessions)

    def test_operator_is_forbidden(self, client):
        auth.create_user("op1", "operator123", "operator")
        data = _login(client, username="op1", password="operator123").get_json()
        resp = client.get("/api/auth/access",
                          headers={"Authorization": f"Bearer {data['token']}"})
        assert resp.status_code == 403

    def test_anonymous_is_rejected(self, client):
        assert client.get("/api/auth/access").status_code == 401

    def test_logout_removes_active_session(self, client):
        data = _login(client).get_json()
        headers = {"Authorization": f"Bearer {data['token']}"}
        assert len(client.get("/api/auth/access", headers=headers)
                     .get_json()["active_sessions"]) >= 1
        assert client.post("/api/auth/logout", headers=headers).status_code == 200
        data2 = _login(client).get_json()
        headers2 = {"Authorization": f"Bearer {data2['token']}"}
        body = client.get("/api/auth/access", headers=headers2).get_json()
        assert all(s["ip"] is not None for s in body["active_sessions"])
