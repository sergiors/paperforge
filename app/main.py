import logging

from fastapi import FastAPI

from .routers import convert, health, sign

logger = logging.getLogger(__name__)

app = FastAPI(debug=True)
app.include_router(health.router)
app.include_router(convert.router)
app.include_router(sign.router)

logger.info('Application started')
