import pytest
from app import entrypoint


@pytest.mark.parametrize('value', ['auto', 'asyncio', 'uvloop'])
def test_named_loop_is_forwarded_to_uvicorn(value: str, monkeypatch):
    # given a Uvicorn loop name in the environment
    monkeypatch.setenv('UVICORN_LOOP', value)
    calls = {}
    monkeypatch.setattr(
        entrypoint.uvicorn,
        'run',
        lambda app, **kwargs: calls.update(kwargs),
    )

    # when the entrypoint starts
    entrypoint.main()

    # then Uvicorn receives that loop name unchanged
    assert calls['loop'] == value


def test_loop_defaults_to_auto(monkeypatch):
    # given UVICORN_LOOP is not set
    monkeypatch.delenv('UVICORN_LOOP', raising=False)
    calls = {}
    monkeypatch.setattr(
        entrypoint.uvicorn,
        'run',
        lambda app, **kwargs: calls.update(kwargs),
    )

    # when the entrypoint starts
    entrypoint.main()

    # then Uvicorn falls back to its native 'auto' selection
    assert calls['loop'] == 'auto'
