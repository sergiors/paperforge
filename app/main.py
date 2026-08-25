import logging

from fastapi import FastAPI

from .routers import convert, health

logger = logging.getLogger(__name__)

app = FastAPI(debug=True)
app.include_router(health.router)
app.include_router(convert.router)

logger.info('Application started')
