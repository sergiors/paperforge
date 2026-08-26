import io
import logging
from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature

# Passphrase for tests/samples/sample.p12.
PASSPHRASE = 'secret'


@pytest.fixture
def p12() -> bytes:
    return (Path(__file__).parent / 'samples/sample.p12').read_bytes()


@pytest.fixture
def pdf() -> bytes:
    return (Path(__file__).parent / 'samples/document.pdf').read_bytes()


def _post(client: TestClient, files: list[tuple[str, bytes]], signers: str):
    return client.post(
        '/pdf/sign',
        files=[('files', (name, content)) for name, content in files],
        data={'signers': signers},
    )


def _signature_statuses(pdf: bytes):
    reader = PdfFileReader(io.BytesIO(pdf))
    return [validate_pdf_signature(sig) for sig in reader.embedded_signatures]


def test_sign_pdf_single_signer(client: TestClient, pdf: bytes, p12: bytes):
    # given a PDF and a PKCS#12 certificate
    files = [('document.pdf', pdf), ('company.p12', p12)]

    # and a signer referencing the certificate
    signers = '[{"file": "company.p12", "passphrase": "secret"}]'

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response is a signed PDF document
    assert response.status_code == HTTPStatus.OK
    assert response.headers['content-type'] == 'application/pdf'
    assert response.content.startswith(b'%PDF-')
    assert len(response.content) > len(pdf)


def test_sign_pdf_multiple_signers(client: TestClient, pdf: bytes, p12: bytes):
    # given a PDF and two PKCS#12 certificates
    files = [
        ('document.pdf', pdf),
        ('company.p12', p12),
        ('manager.p12', p12),
    ]

    # and two signers applied in order
    signers = (
        '[{"file": "company.p12", "passphrase": "secret"},'
        ' {"file": "manager.p12", "passphrase": "secret"}]'
    )

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response is a signed PDF document
    assert response.status_code == HTTPStatus.OK
    assert response.content.startswith(b'%PDF-')
    assert len(response.content) > len(pdf)


def test_sign_pdf_no_pdf(client: TestClient, p12: bytes):
    # given only a PKCS#12 certificate with no PDF
    files = [('company.p12', p12)]

    # and a signer referencing it
    signers = '[{"file": "company.p12", "passphrase": "secret"}]'

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {'error': 'No PDF file was uploaded.'}


def test_sign_pdf_multiple_pdfs(client: TestClient, pdf: bytes, p12: bytes):
    # given two PDF files
    files = [
        ('one.pdf', pdf),
        ('two.pdf', pdf),
        ('company.p12', p12),
    ]

    # and a signer
    signers = '[{"file": "company.p12", "passphrase": "secret"}]'

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {'error': 'More than one PDF file was uploaded.'}


def test_sign_pdf_certificate_not_found(client: TestClient, pdf: bytes, p12: bytes):
    # given a PDF and a PKCS#12 certificate
    files = [('document.pdf', pdf), ('company.p12', p12)]

    # and a signer referencing a file that was not uploaded
    signers = '[{"file": "missing.p12", "passphrase": "secret"}]'

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {
        'error': 'No uploaded file named "missing.p12" was found.'
    }


def test_sign_pdf_invalid_signers_json(client: TestClient, pdf: bytes, p12: bytes):
    # given a PDF and a PKCS#12 certificate
    files = [('document.pdf', pdf), ('company.p12', p12)]

    # and a signers field that is not valid JSON
    signers = '{not valid json'

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert 'Invalid JSON' in response.json()['error']


def test_sign_pdf_signers_not_array(client: TestClient, pdf: bytes, p12: bytes):
    # given a PDF and a PKCS#12 certificate
    files = [('document.pdf', pdf), ('company.p12', p12)]

    # and a signers field that is not a JSON array
    signers = '{"file": "company.p12", "passphrase": "secret"}'

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {'error': '"signers" must be a JSON array.'}


def test_sign_pdf_invalid_passphrase(client: TestClient, pdf: bytes, p12: bytes):
    # given a PDF and a PKCS#12 certificate
    files = [('document.pdf', pdf), ('company.p12', p12)]

    # and a signer with the wrong passphrase
    signers = '[{"file": "company.p12", "passphrase": "wrong"}]'

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert 'Failed to load PKCS#12 file' in response.json()['error']


def test_sign_pdf_invalid_certificate(client: TestClient, pdf: bytes):
    # given a PDF and a file that is not a valid PKCS#12 certificate
    files = [('document.pdf', pdf), ('company.p12', b'not a p12 file')]

    # and a signer referencing it
    signers = '[{"file": "company.p12", "passphrase": "secret"}]'

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert 'Failed to load PKCS#12 file' in response.json()['error']


def test_sign_pdf_invalid_pdf(client: TestClient, p12: bytes):
    # given a corrupt PDF and a PKCS#12 certificate
    files = [('document.pdf', b'%PDF-1.4\nnot a real pdf'), ('company.p12', p12)]

    # and a signer referencing the certificate
    signers = '[{"file": "company.p12", "passphrase": "secret"}]'

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert 'Failed to sign PDF' in response.json()['error']


def test_sign_pdf_signer_not_object(client: TestClient, pdf: bytes, p12: bytes):
    # given a PDF and a PKCS#12 certificate
    files = [('document.pdf', pdf), ('company.p12', p12)]

    # and a signer that is not a JSON object
    signers = '["company.p12"]'

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {'error': 'Each signer must be a JSON object.'}


def test_sign_pdf_signer_missing_file(client: TestClient, pdf: bytes, p12: bytes):
    # given a PDF and a PKCS#12 certificate
    files = [('document.pdf', pdf), ('company.p12', p12)]

    # and a signer without a file
    signers = '[{"passphrase": "secret"}]'

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {
        'error': 'Each signer must have a non-empty "file" string.'
    }


def test_sign_pdf_signer_missing_passphrase(client: TestClient, pdf: bytes, p12: bytes):
    # given a PDF and a PKCS#12 certificate
    files = [('document.pdf', pdf), ('company.p12', p12)]

    # and a signer without a passphrase
    signers = '[{"file": "company.p12"}]'

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {'error': 'Each signer must have a "passphrase" string.'}


def test_sign_pdf_signature_is_valid(client: TestClient, pdf: bytes, p12: bytes):
    # given a PDF and a PKCS#12 certificate
    files = [('document.pdf', pdf), ('company.p12', p12)]

    # and a signer referencing the certificate
    signers = '[{"file": "company.p12", "passphrase": "secret"}]'

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response contains a valid signature
    assert response.status_code == HTTPStatus.OK
    statuses = _signature_statuses(response.content)
    assert len(statuses) == 1
    assert statuses[0].intact
    assert statuses[0].valid


def test_sign_pdf_multiple_signatures_are_valid(
    client: TestClient, pdf: bytes, p12: bytes
):
    # given a PDF and two PKCS#12 certificates
    files = [
        ('document.pdf', pdf),
        ('company.p12', p12),
        ('manager.p12', p12),
    ]

    # and two signers applied in order
    signers = (
        '[{"file": "company.p12", "passphrase": "secret"},'
        ' {"file": "manager.p12", "passphrase": "secret"}]'
    )

    # when I send a POST request to /pdf/sign
    response = _post(client, files, signers)

    # then the response contains two valid signatures
    assert response.status_code == HTTPStatus.OK
    statuses = _signature_statuses(response.content)
    assert len(statuses) == 2
    assert all(status.intact and status.valid for status in statuses)


def test_sign_pdf_unexpected_error(client: TestClient, monkeypatch, caplog):
    # given a request that triggers an unexpected error
    def _raise(*args, **kwargs):
        raise RuntimeError('boom')

    monkeypatch.setattr('app.routers.sign_pdf._sign_pdf', _raise)

    # when I send a POST request to /pdf/sign
    with caplog.at_level(logging.ERROR):
        response = _post(client, [('document.pdf', b'%PDF-1.4')], '[]')

    # then the response is a 500 error and the exception is logged
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.json() == {'error': 'Internal server error.'}
    assert 'Unexpected error during PDF signing' in caplog.text
