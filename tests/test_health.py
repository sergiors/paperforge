from http import HTTPStatus

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient):
    response = client.get('/health')

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {'status': 'ok'}
