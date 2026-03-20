import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager

from asyncpg import Connection, Pool
from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse

router = APIRouter()


class _StreamExhausted:
    pass


@asynccontextmanager
async def subscribe_to_channel(
    pg_pool: Pool,
    channel: str,
) -> AsyncIterator[asyncio.Queue[str | _StreamExhausted]]:
    notifications: asyncio.Queue[str | _StreamExhausted] = asyncio.Queue()
    listener_registered = False

    async with pg_pool.acquire() as connection:

        def listener(
            _connection: Connection,
            _pid: int,
            _channel: str,
            payload: str,
        ) -> None:
            notifications.put_nowait(payload)

        try:
            await connection.add_listener(channel, listener)
            listener_registered = True
            yield notifications
        finally:
            notifications.put_nowait(_StreamExhausted())

            if listener_registered:
                await connection.remove_listener(channel, listener)


def get_pg_pool(request: Request) -> Pool:
    return request.app.state.pg_pool


@router.get('/events', response_class=EventSourceResponse)
async def events(
    request: Request,
    pg_pool: Pool = Depends(get_pg_pool),
) -> AsyncIterable[dict]:
    async with subscribe_to_channel(pg_pool, 'pdf-status') as notifications:
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
