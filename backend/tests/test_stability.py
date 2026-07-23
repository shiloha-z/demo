import json
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.http_stability import install_http_stability
from app.models.models import (
    Agent,
    AgentStatus,
    Base,
    Project,
    Task,
    TaskStatus,
    User,
)
from app.services import execution_service


class HttpStabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        install_http_stability(app)

        @app.get("/ok")
        def ok():
            return {"ok": True}

        @app.get("/boom")
        def boom():
            raise RuntimeError("database password must never reach clients")

        self.client = TestClient(app, raise_server_exceptions=False)

    def test_correlation_headers_are_returned(self) -> None:
        response = self.client.get("/ok", headers={"X-Request-ID": "upstream-123"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "upstream-123")
        self.assertIn("X-Process-Time-Ms", response.headers)

    def test_unhandled_error_is_safe_and_traceable(self) -> None:
        response = self.client.get("/boom")
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["detail"], "服务暂时不可用，请稍后重试")
        self.assertEqual(body["request_id"], response.headers["X-Request-ID"])
        self.assertNotIn("password", json.dumps(body))


class HealthProbeTests(unittest.TestCase):
    def test_readiness_returns_real_503_without_leaking_error(self) -> None:
        from app.main import health_check

        with (
            patch("app.core.database.SessionLocal", side_effect=RuntimeError("secret DSN")),
            patch("subprocess.run"),
        ):
            response = health_check()

        self.assertEqual(response.status_code, 503)
        body = json.loads(response.body)
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["checks"]["database"], "error")
        self.assertNotIn("secret DSN", response.body.decode("utf-8"))


class DatabaseDependencyTests(unittest.TestCase):
    def test_failed_request_rolls_back_and_closes_session(self) -> None:
        session = Mock()
        with patch("app.core.database.SessionLocal", return_value=session):
            dependency = get_db()
            self.assertIs(next(dependency), session)
            with self.assertRaisesRegex(RuntimeError, "failed"):
                dependency.throw(RuntimeError("failed"))
        session.rollback.assert_called_once_with()
        session.close.assert_called_once_with()


class StartupRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        db = self.Session()
        user = User(username="recovery-owner", password_hash="x")
        db.add(user)
        db.flush()
        project = Project(name="Recovery", owner_id=user.id, workspace_path="workspace")
        agent = Agent(
            creator_id=user.id,
            name="Interrupted Agent",
            role="code_gen",
            status=AgentStatus.WORKING,
        )
        db.add_all([project, agent])
        db.flush()
        db.add(Task(
            agent_id=agent.id,
            project_id=project.id,
            title="Interrupted",
            status=TaskStatus.RUNNING,
        ))
        db.commit()
        db.close()

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_interrupted_work_becomes_resumable(self) -> None:
        with patch.object(execution_service, "SessionLocal", self.Session):
            recovered = execution_service.recover_interrupted_agent_runs()

        db = self.Session()
        try:
            self.assertEqual(recovered, 1)
            self.assertEqual(db.query(Task).one().status, TaskStatus.PAUSED)
            self.assertEqual(db.query(Agent).one().status, AgentStatus.IDLE)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
