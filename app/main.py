import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .logging import configure_logging
from .routers import convert_html, health, sign_pdf

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info('Application started')
    yield
    logger.info('Application stopped')


app = FastAPI(debug=True, lifespan=lifespan)
app.include_router(health.router)
app.include_router(convert_html.router)
app.include_router(sign_pdf.router)
