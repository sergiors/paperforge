from http import HTTPStatus

from fastapi.testclient import TestClient

API_KEY = 'my-secret-api-key'


def test_health_is_open_without_api_key(client: TestClient):
    # given authentication is disabled (no API_KEY set)
    # when I send a request to /health without an Authorization header
    response = client.get('/health')

    # then the request is allowed
    assert response.status_code == HTTPStatus.OK


def test_health_is_open_with_api_key(client: TestClient, monkeypatch):
    # given authentication is enabled
    monkeypatch.setenv('API_KEY', API_KEY)

    # when I send a request to /health without an Authorization header
    response = client.get('/health')

    # then the request is allowed
    assert response.status_code == HTTPStatus.OK


def test_convert_allowed_when_api_key_empty(client: TestClient, monkeypatch):
    # given API_KEY is set to an empty string
    monkeypatch.setenv('API_KEY', '')

    # when I send a request to /convert/html without an Authorization header
    response = client.post(
        '/convert/html',
        files=[('files', ('index.html', b'<h1>Hello</h1>'))],
    )

    # then the request is allowed
    assert response.status_code == HTTPStatus.OK


def test_convert_requires_api_key(client: TestClient, monkeypatch):
    # given authentication is enabled
    monkeypatch.setenv('API_KEY', API_KEY)

    # when I send a request to /convert/html without an Authorization header
    response = client.post('/convert/html')

    # then the request is rejected
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json() == {'detail': 'Invalid API key.'}


def test_convert_rejects_invalid_api_key(client: TestClient, monkeypatch):
    # given authentication is enabled
    monkeypatch.setenv('API_KEY', API_KEY)

    # when I send a request to /convert/html with an invalid API key
    response = client.post(
        '/convert/html',
        headers={'Authorization': 'Bearer wrong-key'},
    )

    # then the request is rejected
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json() == {'detail': 'Invalid API key.'}


def test_convert_rejects_malformed_header(client: TestClient, monkeypatch):
    # given authentication is enabled
    monkeypatch.setenv('API_KEY', API_KEY)

    # when I send a request to /convert/html with a malformed Authorization header
    response = client.post(
        '/convert/html',
        headers={'Authorization': 'Basic abc123'},
    )

    # then the request is rejected
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json() == {'detail': 'Invalid API key.'}


def test_convert_accepts_valid_api_key(client: TestClient, monkeypatch):
    # given authentication is enabled
    monkeypatch.setenv('API_KEY', API_KEY)

    # and a valid HTML file
    files = [('files', ('index.html', b'<h1>Hello</h1>'))]

    # when I send a request to /convert/html with the correct API key
    response = client.post(
        '/convert/html',
        headers={'Authorization': f'Bearer {API_KEY}'},
        files=files,
    )

    # then the request is allowed
    assert response.status_code == HTTPStatus.OK


def test_sign_requires_api_key(client: TestClient, monkeypatch):
    # given authentication is enabled
    monkeypatch.setenv('API_KEY', API_KEY)

    # when I send a request to /pdf/sign without an Authorization header
    response = client.post('/pdf/sign')

    # then the request is rejected
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json() == {'detail': 'Invalid API key.'}
