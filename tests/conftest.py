import asyncio
import logging
import os
from typing import Generator

import boto3
import pytest
from app.main import app
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


class PubSub:
    async def subscribe(self, channel):
        self.channel = channel

    async def unsubscribe(self, channel):
        pass

    async def close(self):
        pass

    async def listen(self):
        yield {
            'type': 'message',
            'data': b'started',
        }
        await asyncio.sleep(0)


class Redis:
    def pubsub(self):
        return PubSub()

    async def aclose(self):
        pass


@pytest.fixture
def test_client(s3_client) -> Generator[TestClient, None, None]:

    with TestClient(app) as client:
        client.app.state.s3 = s3_client  # type: ignore
        client.app.state.redis = Redis()  # type: ignore
        yield client
