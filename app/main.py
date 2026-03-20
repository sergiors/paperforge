import os
from contextlib import asynccontextmanager

import asyncpg
import boto3
from fastapi import FastAPI

from .routers import render, sign
from .routers.admin import events as admin_events


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pg_pool = await asyncpg.create_pool(os.getenv('DATABASE_URL'))
    app.state.s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    yield

    await app.state.pg_pool.close()


app = FastAPI(debug=True, lifespan=lifespan)
app.include_router(admin_events, prefix='/admin')
app.include_router(render)
app.include_router(sign)


@app.get('/health')
async def health_check():
    return {'status': 'healthy'}
