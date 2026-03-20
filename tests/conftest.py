import logging
import os
from typing import Generator

import app.main as app_main
import boto3
import pytest
from app import deps
from app.models import Pdf
from app.routers.admin.events import _StreamExhausted
from fastapi.testclient import TestClient
from moto import mock_aws

app = app_main.app


# https://docs.pytest.org/en/7.1.x/reference/reference.html#pytest.hookspec.pytest_configure
def pytest_configure():
    logging.basicConfig(level=logging.INFO)


@pytest.fixture(scope='session')
def aws_credentials():
    os.environ['AWS_ACCESS_KEY_ID'] = 'test'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'test'
    os.environ['AWS_REGION'] = 'us-east-1'


@pytest.fixture
def s3_client(aws_credentials):
    with mock_aws():
        client = boto3.client('s3', region_name='us-east-1')
        client.create_bucket(Bucket='bucket')
        yield client


class Session:
    def __init__(self):
        self.pdfs: dict[object, Pdf] = {}

    def add(self, pdf: Pdf) -> None:
        self.pdfs[pdf.id] = pdf

    async def commit(self) -> None:
        return None

    async def get(self, model, key):
        assert model is Pdf
        return self.pdfs.get(key)


class SessionFactory:
    def __init__(self, session: Session):
        self.session = session

    def __call__(self) -> 'SessionContext':
        return SessionContext(self.session)


class SessionContext:
    def __init__(self, session: Session):
        self.session = session

    async def __aenter__(self) -> Session:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.fixture
def session_factory() -> SessionFactory:
    return SessionFactory(Session())


class Engine:
    def __init__(self):
        self.driver_connection = DriverConnection()

    def connect(self) -> 'EngineConnectionContext':
        return EngineConnectionContext(self.driver_connection)

    async def dispose(self) -> None:
        return None


class EngineConnectionContext:
    def __init__(self, driver_connection: 'DriverConnection'):
        self.connection = EngineConnection(driver_connection)

    async def __aenter__(self) -> 'EngineConnection':
        return self.connection

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class EngineConnection:
    def __init__(self, driver_connection: 'DriverConnection'):
        self.driver_connection = driver_connection

    async def get_raw_connection(self) -> 'RawConnection':
        return RawConnection(self.driver_connection)


class RawConnection:
    def __init__(self, driver_connection: 'DriverConnection'):
        self.driver_connection = driver_connection


class DriverConnection:
    async def add_listener(self, channel: str, callback) -> None:
        callback(self, 1, channel, 'started')
        callback(self, 1, channel, _StreamExhausted())

    async def remove_listener(self, channel: str, callback) -> None:
        return None


@pytest.fixture
def test_client(
    s3_client,
    session_factory: SessionFactory,
    monkeypatch,
) -> Generator[TestClient, None, None]:
    engine = Engine()

    def create_async_engine(*args, **kwargs) -> Engine:
        return engine

    async def setup(*args, **kwargs) -> None:
        return None

    async def get_db_override():
        async with session_factory() as session:
            yield session

    monkeypatch.setattr(app_main, 'create_async_engine', create_async_engine)
    monkeypatch.setattr(app_main, 'setup', setup)

    with TestClient(app) as client:
        client.app.state.s3 = s3_client  # type: ignore
        client.app.state.engine = engine  # type: ignore
        client.app.dependency_overrides[deps.get_db] = get_db_override
        yield client
        client.app.dependency_overrides.clear()
