from app.db.models import Job, Subscription, User


def test_user_tablename():
    assert User.__tablename__ == "users"


def test_subscription_tablename():
    assert Subscription.__tablename__ == "subscriptions"


def test_job_tablename():
    assert Job.__tablename__ == "jobs"


def test_user_columns():
    cols = {c.name for c in User.__table__.columns}
    assert cols == {"id", "email", "name", "google_id", "role", "plan", "created_at"}


def test_job_columns():
    cols = {c.name for c in Job.__table__.columns}
    assert {"id", "user_id", "command", "params", "status", "queued_at", "log_text"} <= cols


def test_job_status_default():
    col = Job.__table__.c.status
    assert col.default.arg == "queued"
