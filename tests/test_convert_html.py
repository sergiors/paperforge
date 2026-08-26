import logging
from http import HTTPStatus
from pathlib import Path

import pytest
from app.routers.convert_html import InvalidFilenameError, _convert_html_to_pdf
from fastapi.testclient import TestClient


@pytest.fixture
def template() -> bytes:
    return (Path(__file__).parent / 'samples/template.html').read_bytes()


def _post(
    client: TestClient,
    files: list[tuple[str, bytes]],
    context: str | None = None,
):
    data = {}
    if context is not None:
        data['context'] = context

    return client.post(
        '/convert/html',
        files=[('files', (name, content)) for name, content in files],
        data=data,
    )


def test_convert_html_without_context(client: TestClient, template: bytes):
    # given a file named "index.html" with HTML content
    files = [('index.html', template)]

    # when I send a POST request to /convert/html
    response = _post(client, files)

    # then the response is a PDF document
    assert response.status_code == HTTPStatus.OK
    assert response.headers['content-type'] == 'application/pdf'
    assert response.content.startswith(b'%PDF-')


def test_convert_html_with_context(client: TestClient, template: bytes):
    # given a file named "index.html" that renders Jinja2 variables
    files = [('index.html', template)]

    # given a context that provides the variables
    context = '{"name": "Sergio", "company": "Paperforge"}'

    # when I send a POST request to /convert/html
    response = _post(client, files, context)

    # then the response is a PDF document
    assert response.status_code == HTTPStatus.OK
    assert response.content.startswith(b'%PDF-')


def test_convert_html_with_assets(client: TestClient):
    # given a file named "index.html" that references a stylesheet
    files = [
        ('index.html', b'<link rel="stylesheet" href="css/style.css"><h1>Hello</h1>'),
        ('css/style.css', b'h1 { color: red; }'),
    ]

    # when I send a POST request to /convert/html
    response = _post(client, files)

    # then the response is a PDF document
    assert response.status_code == HTTPStatus.OK
    assert response.content.startswith(b'%PDF-')


def test_convert_html_missing_index(client: TestClient):
    # given a request without a file named "index.html"
    files = [('style.css', b'h1 { color: red; }')]

    # when I send a POST request to /convert/html
    response = _post(client, files)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {'error': 'No file named "index.html" was uploaded.'}


def test_convert_html_multiple_index(client: TestClient, template: bytes):
    # given two files named "index.html"
    files = [('index.html', template), ('sub/index.html', template)]

    # when I send a POST request to /convert/html
    response = _post(client, files)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {
        'error': 'Exactly one file named "index.html" is required.'
    }


def test_convert_html_invalid_context_json(client: TestClient, template: bytes):
    # given a file named "index.html"
    files = [('index.html', template)]

    # given a context that is not valid JSON
    context = '{not valid json'

    # when I send a POST request to /convert/html
    response = _post(client, files, context)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert 'Invalid JSON' in response.json()['error']


def test_convert_html_context_not_object(client: TestClient, template: bytes):
    # given a file named "index.html"
    files = [('index.html', template)]

    # given a context that is not a JSON object
    context = '[1, 2, 3]'

    # when I send a POST request to /convert/html
    response = _post(client, files, context)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {'error': '"context" must be a JSON object.'}


def test_convert_html_template_error(client: TestClient):
    # given a file named "index.html" that references an undefined variable
    files = [('index.html', b'{{ undefined_var }}')]

    # given an empty context
    context = '{}'

    # when I send a POST request to /convert/html
    response = _post(client, files, context)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert 'Failed to render template' in response.json()['error']


def test_convert_html_missing_asset(client: TestClient):
    # given a file named "index.html" that references a missing asset
    files = [('index.html', b'<img src="missing.png">')]

    # when I send a POST request to /convert/html
    response = _post(client, files)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert 'Failed to load a resource' in response.json()['error']


def test_convert_html_path_traversal(client: TestClient, template: bytes):
    # given a file named "index.html"
    files = [('index.html', template)]

    # given a file with a path traversal filename
    files.append(('../evil.py', b'print(1)'))

    # when I send a POST request to /convert/html
    response = _post(client, files)

    # then the response is a 400 error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {'error': "Invalid filename: '../evil.py'"}


def test_convert_html_empty_filename(template: bytes):
    # given a file named "index.html" and a file with an empty filename
    files = [('index.html', template), ('', b'x')]

    # when I convert the files to PDF
    # then the conversion fails with an invalid filename error
    with pytest.raises(InvalidFilenameError):
        _convert_html_to_pdf(files)


def test_convert_html_unexpected_error(client: TestClient, monkeypatch, caplog):
    # given a request that triggers an unexpected error
    def _raise(*args, **kwargs):
        raise RuntimeError('boom')

    monkeypatch.setattr('app.routers.convert_html._convert_html_to_pdf', _raise)

    # when I send a POST request to /convert/html
    with caplog.at_level(logging.ERROR):
        response = _post(client, [('index.html', b'<h1>Hello</h1>')])

    # then the response is a 500 error and the exception is logged
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.json() == {'error': 'Internal server error.'}
    assert 'Unexpected error during HTML-to-PDF conversion' in caplog.text
