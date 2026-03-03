from http import HTTPStatus

from fastapi.testclient import TestClient


def test_sse_events(test_client: TestClient):
    with test_client.stream('GET', '/admin/events') as response:
        assert response.status_code == HTTPStatus.OK
        assert response.headers['content-type'].startswith('text/event-stream')

        body = next(response.iter_text())

        assert 'started' in body
