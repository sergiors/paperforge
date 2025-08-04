from fastapi.testclient import TestClient
from paperforge.app import app

client = TestClient(app)


def test_read_main():
    response = client.post(
        '/',
        json={
            'template_s3_uri': 's3://saladeaula.digital/billing/template.html',
            'template_vars': {
                'start_date': '2025-07-01',
                'end_date': '2025-07-31',
                'items': [
                    {
                        'author': {
                            'id': 'SMEXYk5MQkKCzknJpxqr8n',
                            'name': 'Jolene',
                        },
                        'course': {
                            'id': 'a810dd22-56c0-4d9b-8cd2-7e2ee9c45839',
                            'name': 'Python',
                        },
                        'created_at': '2025-07-28T12:31:51.333999-03:00',
                        'enrolled_at': '2025-07-21T14:43:33.638645-03:00',
                        'unit_price': '87.2',
                        'user': {
                            'id': 'M6gqXKA39U2jamUX3nT3ur',
                            'name': 'Guido Van Rossum',
                        },
                    },
                    {
                        'author': {
                            'id': 'SMEXYk5MQkKCzknJpxqr8n',
                            'name': 'Jolene',
                        },
                        'course': {
                            'id': '5c119d4b-573c-4d8d-a99d-63756af2f4c5',
                            'name': 'Git',
                        },
                        'created_at': '2025-07-28T12:31:51.595138-03:00',
                        'enrolled_at': '2025-07-15T09:52:21.258157-03:00',
                        'unit_price': 79.2,
                        'user': {
                            'id': '9B1GGHThs3HeHI-oaf5w',
                            'name': 'Linus Torvalds',
                        },
                    },
                    {
                        'author': {
                            'id': 'SMEXYk5MQkKCzknJpxqr8n',
                            'name': 'Jolene',
                        },
                        'course': {
                            'id': '7f7905aa-ec6d-4189-b884-50fa9b1bd0b8',
                            'name': 'Open Source the Right Way',
                        },
                        'created_at': '2025-07-28T12:22:17.856974-03:00',
                        'enrolled_at': '2025-07-04T15:51:10.071593-03:00',
                        'unit_price': 169,
                        'user': {
                            'id': 'l68C18fhWb3eSigHsexD',
                            'name': 'Richard Stallman',
                        },
                    },
                ],
            },
        },
    )

    assert response.status_code == 200

    with open('./test.pdf', 'wb') as f:
        f.write(response.content)
