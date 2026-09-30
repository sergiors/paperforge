import logging
from typing import Generator

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def setup_logging():
    logging.basicConfig(level=logging.INFO)


@pytest.fixture(autouse=True)
def clear_api_key(monkeypatch):
    monkeypatch.delenv('API_KEY', raising=False)


@pytest.fixture(autouse=True)
def reset_pool():
    """Guarantee each test ends without a lingering worker pool."""
    yield
    manager = getattr(app.state, 'worker_pool', None)
    if manager is not None:
        manager.shutdown()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client
