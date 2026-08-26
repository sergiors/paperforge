import json
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment
from weasyprint import HTML
from weasyprint.urls import FatalURLFetchingError, URLFetcher

logger = logging.getLogger(__name__)
router = APIRouter()
jinja_env = SandboxedEnvironment(undefined=StrictUndefined)


class ConversionError(Exception):
    """Base class for HTML-to-PDF conversion errors."""


class MissingIndexHtmlError(ConversionError):
    """No file named ``index.html`` was uploaded."""


class MultipleIndexHtmlError(ConversionError):
    """More than one file named ``index.html`` was uploaded."""


class InvalidContextError(ConversionError):
    """The ``context`` field is not valid JSON or not a JSON object."""


class TemplateRenderError(ConversionError):
    """Rendering ``index.html`` as a Jinja2 template failed."""


class AssetNotFoundError(ConversionError):
    """A resource referenced by the document could not be found."""


class InvalidFilenameError(ConversionError):
    """An uploaded file has an invalid or unsafe filename."""


@router.post('/convert/html')
async def convert_html(
    files: list[UploadFile] = File(...),
    context: str | None = Form(None),
) -> Response:
    uploaded = [(file.filename or '', await file.read()) for file in files]

    try:
        pdf = _convert_html_to_pdf(uploaded, context)
    except ConversionError as exc:
        return JSONResponse(
            status_code=400,
            content={
                'error': str(exc),
            },
        )

    print(pdf)
    return Response(
        content=pdf,
        media_type='application/pdf',
    )


def _convert_html_to_pdf(
    files: list[tuple[str, bytes]],
    context: str | None = None,
) -> bytes | None:
    """Convert uploaded HTML files into a PDF document.

    ``files`` is a list of ``(filename, content)`` pairs. Exactly one file must
    be named ``index.html``; it is the document entry point. Every file is made
    available to the renderer while preserving its relative path.

    ``context`` is an optional JSON string. When provided, ``index.html`` is
    rendered as a Jinja2 template using the parsed object as its context.
    """
    render_context = _parse_context(context)

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        index_path = _write_files(files, root)

        html = index_path.read_text(encoding='utf-8')
        if render_context is not None:
            html = _render_template(html, render_context)
            index_path.write_text(html, encoding='utf-8')

        return _render_pdf(index_path)


def _parse_context(context: str | None) -> dict | None:
    if context is None or not context.strip():
        return None

    try:
        parsed = json.loads(context)
    except json.JSONDecodeError as exc:
        raise InvalidContextError(f'Invalid JSON in "context": {exc}') from exc

    if not isinstance(parsed, dict):
        raise InvalidContextError('"context" must be a JSON object.')

    return parsed


def _write_files(files: list[tuple[str, bytes]], root: Path) -> Path:
    index_names = [name for name, _ in files if Path(name).name == 'index.html']

    if not index_names:
        raise MissingIndexHtmlError('No file named "index.html" was uploaded.')

    if len(index_names) > 1:
        raise MultipleIndexHtmlError('Exactly one file named "index.html" is required.')

    index_path: Path | None = None
    for filename, content in files:
        path = _resolve_path(root, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if path.name == 'index.html':
            index_path = path

    assert index_path is not None  # guaranteed by the check above
    return index_path


def _resolve_path(root: Path, filename: str) -> Path:
    if not filename:
        raise InvalidFilenameError('A file was uploaded without a filename.')

    path = Path(filename)
    if path.is_absolute() or '..' in path.parts:
        raise InvalidFilenameError(f'Invalid filename: {filename!r}')

    return root / path


def _render_template(html: str, context: dict) -> str:
    try:
        template = jinja_env.from_string(html)
        return template.render(**context)
    except TemplateError as exc:
        raise TemplateRenderError(f'Failed to render template: {exc}') from exc


def _render_pdf(index_path: Path) -> bytes | None:
    fetcher = URLFetcher(fail_on_errors=True)
    try:
        document = HTML(
            filename=str(index_path),
            url_fetcher=fetcher,
        )
        return document.write_pdf()
    except FatalURLFetchingError as exc:
        raise AssetNotFoundError(f'Failed to load a resource: {exc}') from exc
