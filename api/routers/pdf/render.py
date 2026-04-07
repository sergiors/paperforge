import os
import tempfile
import uuid
from typing import Annotated
from urllib.parse import urlparse

from botocore.exceptions import ClientError
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from jinja2 import Template
from pydantic import AnyUrl, BaseModel, Field, UrlConstraints
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.background import BackgroundTask
from weasyprint import HTML

from ...deps import S3Client, get_db, get_s3
from ...models import Pdf

router = APIRouter()


class RenderRequest(BaseModel):
    template: Annotated[AnyUrl, UrlConstraints(allowed_schemes=['s3'])]
    vars_: dict[str, str] | None = Field(None, alias='vars')


class PDFResponse(FileResponse):
    media_type = 'application/pdf'


@router.post('/render', response_class=PDFResponse)
async def render(
    render_request: Annotated[RenderRequest, Body()],
    s3_client: S3Client = Depends(get_s3),
    session: AsyncSession = Depends(get_db),
):
    job_id = uuid.uuid7()
    bucket, key = _parse_s3_uri(str(render_request.template))
    vars_ = render_request.vars_ or {}

    await _create_pdf(
        session=session,
        job_id=job_id,
        data={
            'template': str(render_request.template),
            'vars': vars_,
        },
    )
    await _update_pdf_status(session, job_id, 'PROCESSING')

    try:
        obj = s3_client.get_object(Bucket=bucket, Key=key)
    except ClientError as e:
        await _update_pdf_status(
            session,
            job_id,
            'FAILED',
            data={
                'template': str(render_request.template),
                'vars': vars_,
                'error': 'Template not found',
            },
        )
        raise HTTPException(status_code=404, detail='Template not found') from e

    template_html = obj['Body'].read().decode('utf-8')
    html_content = Template(template_html).render(**vars_)

    try:
        tmpfile = await run_in_threadpool(_generate_pdf_to_file, html_content)
    except RuntimeError as e:
        await _update_pdf_status(
            session,
            job_id,
            'FAILED',
            data={
                'template': str(render_request.template),
                'vars': vars_,
                'error': str(e),
            },
        )
        raise HTTPException(status_code=400, detail=str(e)) from e

    await _update_pdf_status(
        session,
        job_id,
        'COMPLETED',
        data={
            'template': str(render_request.template),
            'vars': vars_,
        },
    )

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
            HTML(string=html, base_url='').write_pdf(tmp.name)
            return tmp.name
    except Exception as e:
        raise RuntimeError('PDF generation failed') from e


def _cleanup_file(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


async def _create_pdf(
    session: AsyncSession,
    job_id: uuid.UUID,
    data: dict[str, object],
) -> None:
    pdf = Pdf(
        id=job_id,
        data=data,
    )
    session.add(pdf)
    await session.commit()


async def _update_pdf_status(
    session: AsyncSession,
    job_id: uuid.UUID,
    status: str,
    data: dict[str, object] | None = None,
) -> None:
    pdf = await session.get(Pdf, job_id)

    if pdf is None:
        return

    pdf.status = status

    if data is not None:
        pdf.data = data

    session.add(pdf)
    await session.commit()
