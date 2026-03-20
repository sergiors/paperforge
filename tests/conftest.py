import logging
import os
from typing import Generator

import asyncpg
import boto3
import pytest
import pytest_asyncio
from app.main import app
from app.routers.admin.events import _StreamExhausted
from fastapi.testclient import TestClient
from moto import mock_aws


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


class Pool:
    async def add_listener(self, channel: str, callback):
        callback(self, 1, channel, 'started')
        callback(self, 1, channel, _StreamExhausted())

    async def remove_listener(self, channel: str, callback):
        pass

    async def execute(self, query: str, *args):
        return None

    def acquire(self) -> 'PoolAcquireContext':
        return PoolAcquireContext(self)

    async def close(self):
        pass


class PoolAcquireContext:
    def __init__(self, pool: Pool):
        self.pool = pool

    async def __aenter__(self) -> Pool:
        return self.pool

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest_asyncio.fixture
async def pg_pool() -> Pool:
    return Pool()


@pytest.fixture
def test_client(
    s3_client,
    pg_pool: Pool,
    monkeypatch,
) -> Generator[TestClient, None, None]:
    async def create_pool(*args, **kwargs) -> Pool:
        return pg_pool

    monkeypatch.setattr(asyncpg, 'create_pool', create_pool)

    with TestClient(app) as client:
        client.app.state.s3 = s3_client  # type: ignore
        yield client
