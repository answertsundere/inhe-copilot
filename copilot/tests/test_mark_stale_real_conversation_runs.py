from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.eval_tables import EvalRun
from scripts.mark_stale_real_conversation_runs import mark_stale_runs_abandoned


def _session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'stale_runs.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def test_mark_stale_runs_dry_run_does_not_write_db(tmp_path):
    Session = _session_factory(tmp_path)
    now = datetime(2026, 7, 6, 12, 0, 0)
    db = Session()
    db.add(
        EvalRun(
            run_uid="run-stale",
            source_type="real_conversation",
            status="running",
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
        )
    )
    db.commit()
    db.close()

    result = mark_stale_runs_abandoned(
        older_than_minutes=60,
        reason="test cleanup",
        apply=False,
        now=now,
        db_factory=Session,
    )

    assert result["dry_run"] is True
    assert result["matched_count"] == 1
    assert result["updated_count"] == 0
    db = Session()
    assert db.query(EvalRun).filter_by(run_uid="run-stale").one().status == "running"
    db.close()


def test_mark_stale_runs_apply_only_updates_stale_running_real_runs(tmp_path):
    Session = _session_factory(tmp_path)
    now = datetime(2026, 7, 6, 12, 0, 0)
    db = Session()
    db.add_all(
        [
            EvalRun(
                run_uid="run-stale",
                source_type="real_conversation",
                status="running",
                created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=2),
            ),
            EvalRun(
                run_uid="run-fresh",
                source_type="real_conversation",
                status="running",
                created_at=now - timedelta(minutes=10),
                updated_at=now - timedelta(minutes=10),
            ),
            EvalRun(
                run_uid="run-completed",
                source_type="real_conversation",
                status="completed",
                created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=2),
            ),
            EvalRun(
                run_uid="manual-stale",
                source_type="manual",
                status="running",
                created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=2),
            ),
        ]
    )
    db.commit()
    db.close()

    result = mark_stale_runs_abandoned(
        older_than_minutes=60,
        reason="test cleanup",
        apply=True,
        now=now,
        db_factory=Session,
    )

    assert result["dry_run"] is False
    assert result["matched_count"] == 1
    assert result["updated_count"] == 1
    assert result["updated_run_uids"] == ["run-stale"]

    db = Session()
    stale = db.query(EvalRun).filter_by(run_uid="run-stale").one()
    assert stale.status == "abandoned"
    metadata = stale.get_metadata()
    assert metadata["abandoned_reason"] == "test cleanup"
    assert metadata["status_history"][0]["from"] == "running"
    assert metadata["status_history"][0]["to"] == "abandoned"
    assert db.query(EvalRun).filter_by(run_uid="run-fresh").one().status == "running"
    assert db.query(EvalRun).filter_by(run_uid="run-completed").one().status == "completed"
    assert db.query(EvalRun).filter_by(run_uid="manual-stale").one().status == "running"
    db.close()
