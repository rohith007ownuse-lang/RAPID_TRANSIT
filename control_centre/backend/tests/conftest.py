"""
conftest.py
Shared test fixtures. Every test gets an isolated SQLite database so the
persistence layer never touches the real development database.
"""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import persistence  # noqa: E402
import auth  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path):
    """Point each test at a fresh, empty SQLite database and seed a known
    Admin so auth-protected tests have a baseline user. The real development
    database is never touched."""
    persistence.init_db(path=str(tmp_path / "test.db"), force=True)
    persistence.truncate()
    # Development test admin (admin / admin123); injected outside any env so
    # tests are deterministic regardless of host environment variables.
    admin = auth.create_user("admin", "admin123", auth.ROLE_ADMIN)
    # The event store now correlates events into incidents (Phase 16 wiring
    # in DataStore.add_event), so every test must also start with an empty
    # incident store or incident counts leak between tests.
    from incident_intelligence import incident_store
    incident_store.clear()
    yield admin
    persistence.truncate()
    incident_store.clear()