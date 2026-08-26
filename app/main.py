import logging

from fastapi import FastAPI

from .routers import convert_html, health, sign_pdf

logger = logging.getLogger(__name__)

app = FastAPI(debug=True)
app.include_router(health.router)
app.include_router(convert_html.router)
app.include_router(sign_pdf.router)

logger.info('Application started')
