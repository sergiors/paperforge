from collections.abc import AsyncIterable

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse

router = APIRouter()


def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis


@router.get('/events', response_class=EventSourceResponse)
async def events(
    request: Request,
    redis_client: redis.Redis = Depends(get_redis),
) -> AsyncIterable[dict]:
    pubsub = redis_client.pubsub()
    await pubsub.subscribe('pdf-status')

    try:
        async for message in pubsub.listen():
            if await request.is_disconnected():
                break

            if message['type'] == 'message':
                yield {
                    'event': 'message',
                    'data': message['data'].decode(),
                }
    finally:
        await pubsub.unsubscribe('pdf-status')
        await pubsub.close()
