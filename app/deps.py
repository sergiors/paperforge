from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from fastapi import Request
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from types_boto3_s3.client import S3Client
else:
    S3Client = object


def get_engine(request: Request):
    return request.app.state.engine


def get_s3(request: Request) -> S3Client:
    return request.app.state.s3


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(
        request.app.state.engine, expire_on_commit=False
    ) as session:
        yield session
