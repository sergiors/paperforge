from http import HTTPStatus

from fastapi.testclient import TestClient


def test_sign(test_client: TestClient):
    req = test_client.post(
        '/sign',
        json={
            'pdf': 's3://bucket/template.pdf',
            'signatures': [
                {
                    'pfx': 's3://bucket/sign1.pfx',
                    'passphrase': '123@456',
                }
            ],
        },
    )
    assert req.status_code == HTTPStatus.OK
