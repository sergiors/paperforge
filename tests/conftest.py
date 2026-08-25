import logging
from typing import Generator

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def setup_logging():
    logging.basicConfig(level=logging.INFO)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client
