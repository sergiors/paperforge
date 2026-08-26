import io
import json
import logging

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.misc import PdfReadError
from pyhanko.sign import signers
from pyhanko.sign.signers import SimpleSigner

from ..deps import verify_api_key

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(verify_api_key)])


class SignatureError(Exception):
    """Base class for PDF signing errors."""


class NoPdfError(SignatureError):
    """No PDF file was uploaded."""


class MultiplePdfError(SignatureError):
    """More than one PDF file was uploaded."""


class InvalidSignersError(SignatureError):
    """The ``signers`` field is not valid JSON or has an invalid shape."""


class CertificateNotFoundError(SignatureError):
    """A signer references a file that was not uploaded."""


class InvalidCertificateError(SignatureError):
    """An uploaded PKCS#12 file cannot be loaded."""


class PdfSigningError(SignatureError):
    """The PDF document cannot be signed."""


@router.post('/pdf/sign')
def sign_pdf(
    files: list[UploadFile] = File(...),
    signers: str = Form(...),
) -> Response:
    uploaded = [(file.filename or '', file.file.read()) for file in files]

    try:
        pdf = _sign_pdf(uploaded, signers)
    except SignatureError as exc:
        return JSONResponse(
            status_code=400,
            content={
                'error': str(exc),
            },
        )

    return Response(content=pdf, media_type='application/pdf')


def _sign_pdf(files: list[tuple[str, bytes]], signers_json: str) -> bytes:
    """Sign an uploaded PDF with the uploaded PKCS#12 certificates.

    ``files`` is a list of ``(filename, content)`` pairs. Exactly one file must
    be a PDF document; the rest are the PKCS#12 certificates referenced by the
    ``signers_json`` array. Signatures are applied sequentially in order.
    """
    parsed_signers = _parse_signers(signers_json)

    pdf_files = [content for _, content in files if content.startswith(b'%PDF-')]
    if not pdf_files:
        raise NoPdfError('No PDF file was uploaded.')

    if len(pdf_files) > 1:
        raise MultiplePdfError('More than one PDF file was uploaded.')

    pdf = pdf_files[0]
    file_map = {name: content for name, content in files}

    for index, signer in enumerate(parsed_signers):
        name = signer['file']

        if name not in file_map:
            raise CertificateNotFoundError(
                f'No uploaded file named "{name}" was found.'
            )

        pdf = _apply_signature(
            pdf,
            name,
            file_map[name],
            signer['passphrase'],
            field_name=f'Signature{index + 1}',
        )

    return pdf


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


def _apply_signature(
    pdf: bytes,
    cert_name: str,
    cert: bytes,
    passphrase: str,
    field_name: str,
) -> bytes:
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
