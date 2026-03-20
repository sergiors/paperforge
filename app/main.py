import os
from contextlib import asynccontextmanager

import boto3
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from .routers import render, sign
from .routers.admin import events as admin_events
from .schema import setup


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = create_async_engine(os.getenv('DATABASE_URL'))  # type: ignore
    await setup(app.state.engine)
    app.state.s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    yield

    await app.state.engine.dispose()


app = FastAPI(debug=True, lifespan=lifespan)
app.include_router(admin_events, prefix='/admin')
app.include_router(render)
app.include_router(sign)


@app.get('/health')
async def health_check():
    return {'status': 'healthy'}
