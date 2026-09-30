import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .logging import configure_logging
from .routers import convert_html, health, sign_pdf
from .worker_pool import WorkerPoolManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configure application logging in this (parent) process. Uvicorn has
    # already configured its own loggers by the time the lifespan runs, so
    # ``basicConfig`` only adds a stderr handler for the application loggers
    # when the root logger has none: pool lifecycle and idle-timeout messages
    # are emitted here, not in the worker processes.
    configure_logging()

    # The manager is cheap (no processes); the pool itself and its worker
    # processes are created lazily on the first render or sign request. Each
    # task imports its own dependencies inside the worker that runs it, so
    # WeasyPrint and pyhanko are never imported here.
    app.state.worker_pool = WorkerPoolManager(
        worker_count=int(os.getenv('WORKER_COUNT', 2)),
        idle_timeout=float(os.getenv('WORKER_IDLE_TIMEOUT', 60.0)),
    )
    yield
    app.state.worker_pool.shutdown()


app = FastAPI(debug=True, lifespan=lifespan)
app.include_router(health.router)
app.include_router(convert_html.router)
app.include_router(sign_pdf.router)
