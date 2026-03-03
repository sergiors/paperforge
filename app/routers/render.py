import os
import tempfile
from typing import Annotated
from urllib.parse import urlparse

from botocore.exceptions import ClientError
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from jinja2 import Template
from pydantic import AnyUrl, BaseModel, Field, UrlConstraints
from starlette.background import BackgroundTask
from weasyprint import HTML

from ..boto3clients import S3Client, get_s3_client

router = APIRouter()


class RenderRequest(BaseModel):
    template: Annotated[AnyUrl, UrlConstraints(allowed_schemes=['s3'])]
    vars_: dict[str, str] | None = Field(None, alias='vars')


class PDFResponse(FileResponse):
    media_type = 'application/pdf'


@router.post('/render', response_class=PDFResponse)
async def render(
    render_request: Annotated[RenderRequest, Body()],
    s3_client: S3Client = Depends(get_s3_client),
):
    bucket, key = _parse_s3_uri(str(render_request.template))
    vars_ = render_request.vars_ or {}

    try:
        obj = s3_client.get_object(Bucket=bucket, Key=key)
    except ClientError as e:
        raise HTTPException(status_code=404, detail='Template not found') from e

    template_html = obj['Body'].read().decode('utf-8')
    html_content = Template(template_html).render(**vars_)

    try:
        tmpfile = await run_in_threadpool(_generate_pdf_to_file, html_content)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return PDFResponse(
        tmpfile,
        filename='filename.pdf',
        background=BackgroundTask(_cleanup_file, tmpfile),
    )


def _parse_s3_uri(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    return parsed.netloc, parsed.path.lstrip('/')


def _generate_pdf_to_file(html: str) -> str:
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            HTML(string=html).write_pdf(tmp.name)
            return tmp.name
    except Exception as e:
        raise RuntimeError('PDF generation failed') from e


def _cleanup_file(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
