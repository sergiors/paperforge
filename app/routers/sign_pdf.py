import io
import json
import logging
import time
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response

from ..deps import get_worker_pool, verify_api_key
from ..worker_pool import WorkerPool

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(verify_api_key)])


class SignatureError(Exception):
    """Base class for PDF signing errors."""


class NoPdfError(SignatureError):
    """No PDF file was uploaded."""


class MultiplePdfError(SignatureError):
    """More than one PDF file was uploaded."""


class InvalidSignersError(SignatureError):
    """The signers field is invalid."""


class InvalidStampError(SignatureError):
    """The stamp field is invalid or cannot be applied."""


class CertificateNotFoundError(SignatureError):
    """A signer references a file that was not uploaded."""


class InvalidCertificateError(SignatureError):
    """An uploaded PKCS#12 file cannot be loaded."""


class PdfSigningError(SignatureError):
    """The PDF document cannot be signed."""


@router.post('/pdf/sign')
def sign_pdf(
    worker_pool: Annotated[WorkerPool, Depends(get_worker_pool)],
    files: list[UploadFile] = File(...),
    signers: str = Form(...),
    stamp: str = Form(''),
) -> Response:
    uploaded = [(file.filename or '', file.file.read()) for file in files]

    start = time.perf_counter()
    try:
        pdf = _sign_pdf(uploaded, signers, worker_pool, stamp)
    except SignatureError as exc:
        logger.warning('PDF signing failed: %s', exc)
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content={
                'error': str(exc),
            },
        )
    except Exception:
        logger.exception('Unexpected error during PDF signing')
        return JSONResponse(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content={
                'error': 'Internal server error.',
            },
        )

    logger.info('Signed PDF in %.3fs', time.perf_counter() - start)
    return Response(content=pdf, media_type='application/pdf')


def _sign_pdf(
    files: list[tuple[str, bytes]],
    signers_json: str,
    pool: WorkerPool,
    stamp_json: str = '',
) -> bytes:
    """Sign an uploaded PDF with the uploaded PKCS#12 certificates.

    ``files`` is a list of ``(filename, content)`` pairs. Exactly one file must
    be a PDF document; the rest are the PKCS#12 certificates referenced by the
    ``signers_json`` array. Signatures are applied sequentially in order.

    ``pool`` applies the stamp and signatures in a worker process: parsing and
    validation run here, so malformed requests fail fast without starting
    the pool.
    """
    parsed_signers = _parse_signers(signers_json)
    stamp = _parse_stamp(stamp_json)

    logger.info('Signing PDF with %d signer(s)', len(parsed_signers))

    pdf_files = [content for _, content in files if content.startswith(b'%PDF-')]

    if not pdf_files:
        raise NoPdfError('No PDF file was uploaded.')

    if len(pdf_files) > 1:
        raise MultiplePdfError('More than one PDF file was uploaded.')

    pdf = pdf_files[0]
    file_map = {name: content for name, content in files}

    jobs = []
    for signer in parsed_signers:
        name = signer['file']

        if name not in file_map:
            raise CertificateNotFoundError(
                f'No uploaded file named "{name}" was found.'
            )

        jobs.append((name, file_map[name], signer['passphrase']))

    return pool.submit(_apply_signatures, pdf, jobs, stamp).result()


def _parse_signers(signers_json: str) -> list[dict]:
    try:
        parsed = json.loads(signers_json)
    except json.JSONDecodeError as exc:
        raise InvalidSignersError(f'Invalid JSON in "signers": {exc}') from exc

    if not isinstance(parsed, list):
        raise InvalidSignersError('"signers" must be a JSON array.')

    result = []
    for item in parsed:
        if not isinstance(item, dict):
            raise InvalidSignersError('Each signer must be a JSON object.')

        file = item.get('file')
        passphrase = item.get('passphrase')

        if not isinstance(file, str) or not file:
            raise InvalidSignersError(
                'Each signer must have a non-empty "file" string.'
            )

        if not isinstance(passphrase, str):
            raise InvalidSignersError('Each signer must have a "passphrase" string.')

        result.append({'file': file, 'passphrase': passphrase})

    return result


def _parse_stamp(stamp_json: str) -> dict | None:
    if not stamp_json.strip():
        return None

    try:
        parsed = json.loads(stamp_json)
    except json.JSONDecodeError as exc:
        raise InvalidStampError(f'Invalid JSON in "stamp": {exc}') from exc

    if not isinstance(parsed, dict):
        raise InvalidStampError('"stamp" must be a JSON object.')

    anchor = parsed.get('anchor')
    text = parsed.get('text')

    if not isinstance(anchor, str) or not anchor.strip():
        raise InvalidStampError('The stamp must have a non-empty "anchor" string.')

    if not isinstance(text, str) or not text.strip():
        raise InvalidStampError('The stamp must have a non-empty "text" string.')

    return {'anchor': anchor, 'text': text}


def _apply_stamp(pdf: bytes, stamp: dict) -> bytes:
    import pymupdf
    from pyhanko.pdf_utils.misc import PdfReadError
    from pyhanko.pdf_utils.reader import PdfFileReader

    try:
        embedded_signatures = PdfFileReader(io.BytesIO(pdf)).embedded_signatures
    except (PdfReadError, ValueError) as exc:
        raise InvalidStampError(f'Failed to read PDF for stamping: {exc}') from exc

    if embedded_signatures:
        raise InvalidStampError('Cannot stamp an already signed PDF.')

    try:
        document = pymupdf.open(stream=pdf, filetype='pdf')
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise InvalidStampError(f'Failed to read PDF for stamping: {exc}') from exc

    anchor = stamp['anchor']
    text = stamp['text']

    with document:
        if document.is_encrypted or document.needs_pass:
            raise InvalidStampError('Cannot stamp an encrypted PDF.')

        try:
            matches = [
                (page, rect) for page in document for rect in page.search_for(anchor)
            ]

            if not matches:
                raise InvalidStampError(f'Anchor "{anchor}" not found.')

            if len(matches) > 1:
                raise InvalidStampError(f'Anchor "{anchor}" is ambiguous.')

            page, rect = matches[0]
            fontsize = 8
            lines = text.splitlines()

            width = (
                max(
                    pymupdf.get_text_length(
                        line,
                        fontname='helv',
                        fontsize=fontsize,
                    )
                    for line in lines
                )
                + 2
            )

            height = fontsize * (len(lines) + 1.5)
            center = (rect.x0 + rect.x1) / 2

            box = pymupdf.Rect(
                center - width / 2,
                rect.y1 - height,
                center + width / 2,
                rect.y1,
            )

            if (box * page.rotation_matrix) not in page.rect:
                raise InvalidStampError(f'Stamp "{anchor}" exceeds page bounds.')

            page.add_redact_annot(
                rect,
                fill=False,  # type: ignore  # False disables fill.
                cross_out=False,
            )
            page.apply_redactions(images=0, graphics=0)

            remaining = page.insert_textbox(
                box,
                text,
                fontname='helv',
                fontsize=fontsize,
                color=(0, 0, 0),
                align=pymupdf.TEXT_ALIGN_CENTER,
            )

            if remaining < 0:
                raise InvalidStampError(f'Stamp "{anchor}" does not fit.')

            logger.info('Applied stamp "%s"', anchor)

            return document.tobytes(garbage=4, deflate=True)
        except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
            raise InvalidStampError(f'Failed to apply stamp: {exc}') from exc


def _apply_signature(
    pdf: bytes,
    cert_name: str,
    cert: bytes,
    passphrase: str,
    field_name: str,
) -> bytes:
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.misc import PdfReadError
    from pyhanko.sign import signers
    from pyhanko.sign.signers import SimpleSigner

    try:
        signer = SimpleSigner.load_pkcs12_data(
            cert,
            other_certs=[],
            passphrase=passphrase.encode(),
        )
    except ValueError as exc:
        cause = exc.__cause__
        detail = str(cause) if cause else str(exc)
        raise InvalidCertificateError(
            f'Failed to load PKCS#12 file "{cert_name}": {detail}'
        ) from exc

    try:
        writer = IncrementalPdfFileWriter(io.BytesIO(pdf))
        output = signers.sign_pdf(
            writer,
            signers.PdfSignatureMetadata(field_name=field_name),
            signer=signer,
        )
    except (PdfReadError, ValueError) as exc:
        raise PdfSigningError(f'Failed to sign PDF: {exc}') from exc

    return output.getvalue()


def _apply_signatures(
    pdf: bytes,
    jobs: list[tuple[str, bytes, str]],
    stamp: dict | None = None,
) -> bytes:
    """Apply the optional stamp and then signatures to ``pdf`` in order.

    Runs inside a worker process. ``jobs`` is a list of
    ``(cert_name, cert, passphrase)`` triples, so only pickle-safe values
    cross the process boundary. Errors that map to a client error are
    raised as application-level exceptions and travel back to the parent
    process with the job result.

    pyHanko and PyMuPDF are imported inside the worker task functions, so
    they are not loaded by FastAPI.
    """
    if stamp:
        pdf = _apply_stamp(pdf, stamp)

    for index, (name, cert, passphrase) in enumerate(jobs):
        logger.info('Applying signature %d (%s)', index + 1, name)
        pdf = _apply_signature(
            pdf,
            name,
            cert,
            passphrase,
            field_name=f'Signature{index + 1}',
        )

    return pdf
