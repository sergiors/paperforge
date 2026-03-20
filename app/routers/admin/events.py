import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from ...deps import get_engine

router = APIRouter()


class _StreamExhausted:
    pass


@asynccontextmanager
async def subscribe_to_channel(
    engine: AsyncEngine,
    channel: str,
) -> AsyncIterator[asyncio.Queue[str | _StreamExhausted]]:
    listener_registered = False
    notifications: asyncio.Queue[str | _StreamExhausted] = asyncio.Queue()

    async with engine.connect() as connection:
        raw_connection = await connection.get_raw_connection()
        driver_connection = raw_connection.driver_connection
        assert driver_connection is not None

        def listener(
            _connection,
            _pid: int,
            _channel: str,
            payload: str,
        ) -> None:
            notifications.put_nowait(payload)

        try:
            await driver_connection.add_listener(channel, listener)
            listener_registered = True
            yield notifications
        finally:
            notifications.put_nowait(_StreamExhausted())

            if listener_registered:
                await driver_connection.remove_listener(channel, listener)


@router.get('/events', response_class=EventSourceResponse)
async def events(
    request: Request,
    engine: AsyncEngine = Depends(get_engine),
) -> AsyncIterable[dict]:
    async with subscribe_to_channel(engine, 'pdf-status') as notifications:
        while True:
            if await request.is_disconnected():
                break

            try:
                payload = await asyncio.wait_for(
                    notifications.get(),
                    timeout=1,
                )
            except TimeoutError:
                continue

            if isinstance(payload, _StreamExhausted):
                break

            yield {
                'event': 'message',
                'data': payload,
            }
