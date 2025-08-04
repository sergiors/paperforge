import locale
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from http import HTTPStatus
from io import BytesIO
from typing import Annotated

from fastapi import Body, FastAPI, Response
from fastapi.responses import StreamingResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel
from weasyprint import HTML

from .boto3clients import s3_client
from .s3 import download_from_s3

locale.setlocale(locale.LC_ALL, os.getenv('LC_LOCALE', ''))


app = FastAPI()


class PDFDocument(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    template_s3_uri: str
    template_vars: dict = Field(sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def currency(value: float | int | Decimal) -> str:
    if isinstance(value, str):
        value = Decimal(value)

    return locale.currency(value, grouping=True)


def datetime_format(dt: date | str, fmt='%H:%M %d-%m-%y'):
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)

    return dt.strftime(fmt)


@app.post('/')
async def pdf(doc: Annotated[PDFDocument, Body()]):
    template_path = download_from_s3(doc.template_s3_uri, s3_client=s3_client)

    env = Environment(loader=FileSystemLoader(os.path.dirname(template_path)))
    env.filters['datetime_format'] = datetime_format
    env.filters['currency'] = currency

    template = env.get_template(os.path.basename(template_path))
    html_content = template.render(**doc.template_vars)
    pdf_bytes = HTML(string=html_content, base_url='').write_pdf()

    if not pdf_bytes:
        return Response(status_code=HTTPStatus.BAD_REQUEST)

    return StreamingResponse(
        content=BytesIO(pdf_bytes),
        media_type='application/pdf',
        headers={
            'Content-Disposition': 'attachment; filename="filename.pdf"',
        },
    )
