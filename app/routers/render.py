import io
from typing import Annotated
from urllib.parse import urlparse

from botocore.exceptions import ClientError
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from jinja2 import Template
from pydantic import AnyUrl, BaseModel, Field, UrlConstraints
from weasyprint import HTML

from ..boto3clients import S3Client, get_s3_client

router = APIRouter()


class RenderRequest(BaseModel):
    template: Annotated[AnyUrl, UrlConstraints(allowed_schemes=['s3'])]
    vars_: dict[str, str] | None = Field(None, alias='vars')


@router.post('/render', response_class=StreamingResponse)
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
    template = Template(template_html)
    html_content = template.render(**vars_)

    try:
        pdf_bytes = await run_in_threadpool(_generate_pdf, html_content)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type='application/pdf',
        headers={
            'Content-Disposition': 'attachment; filename="filename.pdf"',
        },
    )


def _parse_s3_uri(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    return parsed.netloc, parsed.path.lstrip('/')


def _generate_pdf(html: str) -> bytes:
    try:
        pdf = HTML(string=html, base_url='').write_pdf()
    except Exception as e:
        raise RuntimeError('PDF generation failed') from e

    if pdf is None:
        raise RuntimeError('PDF generation returned None')

    return pdf
