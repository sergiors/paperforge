import importlib
from http import HTTPStatus
from pathlib import Path

from app.models import Pdf
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
        '/pdf/render',
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


def test_render_tracks_job_statuses(
    test_client: TestClient, s3_client, session_factory
):
    s3_client.put_object(
        Bucket='bucket',
        Key='template.html',
        Body=b'<html>Hello {{ name }}</html>',
    )

    response = test_client.post(
        '/pdf/render',
        json={
            'template': 's3://bucket/template.html',
            'vars': {'name': 'John'},
        },
    )

    session = session_factory.session

    assert response.status_code == HTTPStatus.OK
    assert len(session.pdfs) == 1
    pdf = next(iter(session.pdfs.values()))
    assert isinstance(pdf, Pdf)
    assert pdf.status == 'COMPLETED'
    assert pdf.data == {
        'template': 's3://bucket/template.html',
        'vars': {'name': 'John'},
    }


def test_render_executes_cleanup_after_response(
    monkeypatch, test_client: TestClient, s3_client
):
    route = importlib.import_module('app.routers.pdf.render')
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
        '/pdf/render',
        json={'template': 's3://bucket/template.html'},
    )

    # Ensures the execution of the BackgroundTask
    _ = response.content

    assert called


def test_render_returns_404_when_template_not_found(
    test_client: TestClient,
    s3_client,
    session_factory,
):
    req = test_client.post(
        '/pdf/render',
        json={
            'template': 's3://bucket/template.html',
            'vars': {'name': 'John'},
        },
    )

    assert req.status_code == HTTPStatus.NOT_FOUND
    pdf = next(iter(session_factory.session.pdfs.values()))
    assert pdf.status == 'FAILED'
    assert pdf.data == {
        'template': 's3://bucket/template.html',
        'vars': {'name': 'John'},
        'error': 'Template not found',
    }
