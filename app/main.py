import os
from contextlib import asynccontextmanager

import boto3
import redis.asyncio as redis
from fastapi import FastAPI

from .routers import render, sign
from .routers.admin import events


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost'))
    app.state.s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    yield
    await app.state.redis.aclose()


app = FastAPI(debug=True, lifespan=lifespan)
app.include_router(events, prefix='/admin')
app.include_router(render)
app.include_router(sign)


@app.get('/health')
async def health_check():
    return {'status': 'healthy'}
