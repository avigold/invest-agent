import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from jose import jwt

from app.api.routes_jobs import init_job_globals
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.api.deps import get_current_user
from app.jobs.queue import JobQueue
from app.jobs.registry import JobRegistry, LiveJob
from app.main import app


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_user(plan: str = "free", role: str = "user") -> User:
    u = User(
        id=uuid.uuid4(),
        email="test@example.com",
        name="Test",
        plan=plan,
        role=role,
    )
    return u


def _setup_job_globals():
    """Create a fresh registry + queue for testing."""
    registry = JobRegistry()
    job_queue = JobQueue(max_concurrent=4)

    # Dummy run_fn that just completes immediately
    async def _dummy_run(job: LiveJob):
        job.status = "done"
        job.finished_at = datetime.now(tz=timezone.utc)
        job.log_lines.append("test done")
        job.queue.put("test done")
        job.queue.put(None)

    init_job_globals(registry, job_queue, _dummy_run)
    return registry, job_queue


def _mock_db():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 0  # count_monthly_jobs
    mock_session.execute.return_value = mock_result

    async def override_get_db():
        yield mock_session

    return override_get_db


def _mock_user(user: User):
    async def override():
        return user
    return override


# ---------------------------------------------------------------------------
# Unit tests: registry
# ---------------------------------------------------------------------------


def test_registry_create():
    registry = JobRegistry()
    uid = uuid.uuid4()
    job = registry.create("echo", {"message": "hi"}, uid)
    assert job.status == "queued"
    assert job.command == "echo"
    assert job.user_id == uid


def test_registry_get():
    registry = JobRegistry()
    uid = uuid.uuid4()
    job = registry.create("echo", {}, uid)
    found = registry.get(job.id)
    assert found is job


def test_registry_list_for_user():
    registry = JobRegistry()
    uid = uuid.uuid4()
    other_uid = uuid.uuid4()
    registry.create("echo", {}, uid)
    registry.create("echo", {}, other_uid)
    registry.create("echo", {}, uid)
    assert len(registry.list_for_user(uid)) == 2
    assert len(registry.list_for_user(other_uid)) == 1


def test_registry_has_running_job():
    registry = JobRegistry()
    uid = uuid.uuid4()
    job = registry.create("echo", {}, uid)
    # queued counts as "has running"
    assert registry.has_running_job(uid)
    job.status = "done"
    assert not registry.has_running_job(uid)


def test_registry_mark_cancelled():
    registry = JobRegistry()
    uid = uuid.uuid4()
    job = registry.create("echo", {}, uid)
    job.status = "running"
    assert registry.mark_cancelled(job.id)
    assert job.status == "cancelled"


def test_registry_mark_cancelled_done_job():
    registry = JobRegistry()
    uid = uuid.uuid4()
    job = registry.create("echo", {}, uid)
    job.status = "done"
    assert not registry.mark_cancelled(job.id)


# ---------------------------------------------------------------------------
# Unit tests: queue
# ---------------------------------------------------------------------------


def test_queue_light_job_bypasses():
    queue = JobQueue(max_concurrent=1)
    registry = JobRegistry()
    uid = uuid.uuid4()
    job = registry.create("echo", {}, uid)  # echo is light

    started = []

    async def run(j):
        started.append(j.id)
        j.status = "done"
        j.queue.put(None)

    queue.enqueue(job, registry, run)
    # Light jobs start immediately
    import time
    time.sleep(0.5)
    assert job.id in started


def test_queue_position():
    jq = JobQueue(max_concurrent=0)  # no slots
    registry = JobRegistry()
    uid = uuid.uuid4()

    async def noop(j): pass

    j1 = registry.create("country_refresh", {}, uid)
    j2 = registry.create("country_refresh", {}, uid)
    jq.enqueue(j1, registry, noop)
    jq.enqueue(j2, registry, noop)
    assert jq.queue_position(j1.id) == 1
    assert jq.queue_position(j2.id) == 2
    assert jq.queue_position(uuid.uuid4()) is None


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


def test_create_job_api():
    user = _make_user()
    registry, _ = _setup_job_globals()
    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = _mock_db()

    client = TestClient(app)
    try:
        r = client.post("/api/jobs", json={"command": "echo", "params": {"message": "hello"}})
        assert r.status_code == 200
        data = r.json()
        assert data["command"] == "echo"
        assert data["status"] in ("queued", "running", "done")
    finally:
        app.dependency_overrides.clear()


def test_list_jobs_api():
    user = _make_user()
    registry, _ = _setup_job_globals()
    # Pre-create a job
    registry.create("echo", {}, user.id)

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = _mock_db()

    client = TestClient(app)
    try:
        r = client.get("/api/jobs")
        assert r.status_code == 200
        assert len(r.json()) >= 1
    finally:
        app.dependency_overrides.clear()


def test_get_job_api():
    user = _make_user()
    registry, _ = _setup_job_globals()
    job = registry.create("echo", {}, user.id)

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = _mock_db()

    client = TestClient(app)
    try:
        r = client.get(f"/api/jobs/{job.id}")
        assert r.status_code == 200
        assert r.json()["id"] == str(job.id)
    finally:
        app.dependency_overrides.clear()


def test_get_job_not_found():
    user = _make_user()
    _setup_job_globals()
    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = _mock_db()

    client = TestClient(app)
    try:
        r = client.get(f"/api/jobs/{uuid.uuid4()}")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_concurrent_job_limit():
    user = _make_user()
    registry, _ = _setup_job_globals()
    # Create a running job
    job = registry.create("echo", {}, user.id)
    job.status = "running"

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = _mock_db()

    client = TestClient(app)
    try:
        r = client.post("/api/jobs", json={"command": "echo", "params": {}})
        assert r.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_cancel_job_api():
    user = _make_user()
    registry, _ = _setup_job_globals()
    job = registry.create("echo", {}, user.id)
    job.status = "running"

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = _mock_db()

    client = TestClient(app)
    try:
        r = client.post(f"/api/jobs/{job.id}/cancel")
        assert r.status_code == 200
        assert job.status == "cancelled"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Echo handler test
# ---------------------------------------------------------------------------


def test_echo_handler():
    from app.jobs.handlers.echo import echo_handler

    job = LiveJob(
        id=uuid.uuid4(),
        command="echo",
        params={"message": "hello world"},
        status="running",
        user_id=uuid.uuid4(),
        queued_at=datetime.now(tz=timezone.utc),
    )
    mock_factory = AsyncMock()
    asyncio.get_event_loop().run_until_complete(echo_handler(job, mock_factory))

    assert len(job.log_lines) == 3  # "hello", "world", "Done."
    assert job.log_lines[0] == "[1] hello"
    assert job.log_lines[-1] == "Done."
