"""Integration tests for apps.api.health_router."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.health_router import create_health_router


def _build_app(*, ready: bool, accepting_jobs: bool) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_health_router(
            workspace_dir="/tmp",  # noqa: S108 — value is bypassed by readiness_provider
            database_locator="sqlite:///:memory:",
            site_secrets={},
            worker_count=1,
            security_disabled=True,
            dispatcher_accepting_jobs=lambda: accepting_jobs,
            readiness_provider=lambda: {"ready": ready},
        )
    )
    return TestClient(app)


def test_health_live_always_returns_ok() -> None:
    client = _build_app(ready=True, accepting_jobs=True)
    assert client.get("/health/live").json() == {"status": "ok"}


def test_health_returns_ready_when_runtime_is_ready_and_dispatcher_accepting() -> None:
    client = _build_app(ready=True, accepting_jobs=True)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dispatcher_accepting_jobs": True,
    }


def test_health_ready_alias_returns_same_payload() -> None:
    client = _build_app(ready=True, accepting_jobs=True)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dispatcher_accepting_jobs": True,
    }


def test_health_returns_not_ready_when_runtime_is_not_ready() -> None:
    client = _build_app(ready=False, accepting_jobs=True)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dispatcher_accepting_jobs": True,
    }


def test_health_reflects_paused_dispatcher_state() -> None:
    client = _build_app(ready=True, accepting_jobs=False)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dispatcher_accepting_jobs": False,
    }
