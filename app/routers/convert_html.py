import asyncio
import json
import logging
import tempfile
import time
from http import HTTPStatus
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from ..deps import get_worker_pool, verify_api_key
from ..worker_pool import WorkerPool

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(verify_api_key)])
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
    worker_pool: Annotated[WorkerPool, Depends(get_worker_pool)],
    files: Annotated[list[UploadFile], File()],
    context: Annotated[str | None, Form()] = None,
) -> Response:
    uploaded = [(file.filename or '', await file.read()) for file in files]

    start = time.perf_counter()
    loop = asyncio.get_running_loop()
    try:
        # Run the conversion (and the process-pool render inside it) in a
        # worker thread so the event loop is never blocked.
        pdf = await loop.run_in_executor(
            None,
            _convert_html_to_pdf,
            uploaded,
            context,
            worker_pool,
        )
    except ConversionError as exc:
        logger.warning('HTML-to-PDF conversion failed: %s', exc)
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content={
                'error': str(exc),
            },
        )
    except Exception:
        logger.exception('Unexpected error during HTML-to-PDF conversion')
        return JSONResponse(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content={'error': 'Internal server error.'},
        )

    logger.info('Converted HTML to PDF in %.3fs', time.perf_counter() - start)
    return Response(
        content=pdf,
        media_type='application/pdf',
    )


def _convert_html_to_pdf(
    files: list[tuple[str, bytes]],
    context: str | None,
    pool: WorkerPool,
) -> bytes | None:
    """Convert uploaded HTML files into a PDF document.

    ``files`` is a list of ``(filename, content)`` pairs. Exactly one file
    must be named ``index.html``; it is the document entry point. Every file
    is made available to the renderer while preserving its relative path.

    ``context`` is an optional JSON string. When provided, ``index.html`` is
    rendered as a Jinja2 template using the parsed object as its context.

    ``pool`` renders the document in a worker process.
    """
    render_context = _parse_context(context)

    with tempfile.TemporaryDirectory() as tmp_dir:
        index_path = _write_files(files, Path(tmp_dir))
        html = index_path.read_text(encoding='utf-8')

        if render_context is not None:
            logger.info('Rendering HTML template')
            html = _render_template(html, render_context)
            index_path.write_text(html, encoding='utf-8')
        else:
            logger.debug('Skipping template rendering (no context)')

        # The temporary directory stays alive until the worker finished
        # rendering; only the plain path string crosses the process
        # boundary.
        return pool.submit(_render_pdf, str(index_path)).result()


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


def _render_pdf(index_path: str) -> bytes | None:
    """Render the HTML file at ``index_path`` to a PDF document.

    Runs inside a worker process. ``index_path`` is a plain string so only
    pickle-safe values cross the process boundary. Errors that map to a
    client error are raised as application-level exceptions and travel back
    to the parent process with the job result.

    WeasyPrint is imported here, so it is only ever loaded by the workers
    that actually render; the FastAPI process never imports it.
    """
    from weasyprint import HTML
    from weasyprint.urls import FatalURLFetchingError, URLFetcher

    logger.info('Generating PDF')
    fetcher = URLFetcher(fail_on_errors=True)
    try:
        document = HTML(
            filename=index_path,
            url_fetcher=fetcher,
        )
        return document.write_pdf()
    except FatalURLFetchingError as exc:
        raise AssetNotFoundError(f'Failed to load a resource: {exc}') from exc
