import importlib
from http import HTTPStatus
from pathlib import Path

from fastapi.testclient import TestClient


def test_render_returns_pdf_when_template_exists(test_client: TestClient, s3_client):
    template_path = Path('tests/samples/template.html')
    content = template_path.read_bytes()

    s3_client.put_object(
        Bucket='bucket',
        Key='template.html',
        Body=content,
    )

    response = test_client.post(
        '/render',
        json={
            'template': 's3://bucket/template.html',
            'vars': {'name': 'John'},
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert response.headers['content-type'] == 'application/pdf'
    assert (
        response.headers['content-disposition'] == 'attachment; filename="filename.pdf"'
    )

    assert response.content.startswith(b'%PDF')
    assert len(response.content) > 100


def test_render_executes_cleanup_after_response(
    monkeypatch, test_client: TestClient, s3_client
):
    route = importlib.import_module('app.routers.render')
    called = False

    def cleanup_file(path):
        nonlocal called
        called = True

    monkeypatch.setattr(route, '_cleanup_file', cleanup_file)

    s3_client.put_object(
        Bucket='bucket',
        Key='template.html',
        Body=b'<html>Hello</html>',
    )

    response = test_client.post(
        '/render',
        json={'template': 's3://bucket/template.html'},
    )

    # Ensures the execution of the BackgroundTask
    _ = response.content

    assert called


def test_render_returns_404_when_template_not_found(test_client: TestClient, s3_client):
    req = test_client.post(
        '/render',
        json={
            'template': 's3://bucket/template.html',
            'vars': {'name': 'John'},
        },
    )

    assert req.status_code == HTTPStatus.NOT_FOUND
