from http import HTTPStatus
from pathlib import Path

from fastapi.testclient import TestClient


def test_render(test_client: TestClient, s3_client):
    template_path = Path('tests/samples/template.html')
    content = template_path.read_bytes()

    s3_client.put_object(
        Bucket='bucket',
        Key='template.html',
        Body=content,
    )

    req = test_client.post(
        '/render',
        json={
            'template': 's3://bucket/template.html',
            'vars': {'name': 'John'},
        },
    )

    assert req.status_code == HTTPStatus.OK
    assert req.headers['content-type'] == 'application/pdf'
    assert req.content.startswith(b'%PDF')


def test_template_not_found(test_client: TestClient, s3_client):
    req = test_client.post(
        '/render',
        json={
            'template': 's3://bucket/template.html',
            'vars': {'name': 'John'},
        },
    )

    assert req.status_code == HTTPStatus.NOT_FOUND
