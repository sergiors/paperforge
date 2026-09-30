import logging
import multiprocessing
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from http import HTTPStatus
from pathlib import Path

import pytest
from app.main import app
from app.routers.convert_html import _render_pdf
from app.routers.sign_pdf import _apply_signatures
from app.worker_pool import WorkerPool, WorkerPoolManager
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


def _post(client: TestClient, files: list[tuple[str, bytes]]):
    return client.post(
        '/convert/html',
        files=[('files', (name, content)) for name, content in files],
    )


def current_pool() -> WorkerPool | None:
    """Return the application's shared pool, if it has been created."""
    manager = getattr(app.state, 'worker_pool', None)
    if manager is None:
        return None
    return manager.current()


def wait_until(
    predicate,
    *,
    timeout: float = 20.0,
    message: str = 'condition not met',
) -> None:
    """Poll ``predicate`` until true, failing instead of sleeping blindly."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(message)


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _worker_pid() -> int:
    """Run inside a worker: report which process executed the job."""
    return os.getpid()


def _raise_worker_error() -> None:
    """Run inside a worker: fail with an unexpected error."""
    raise ValueError('worker-side failure')


def _worker_heavy_imports() -> tuple[bool, bool]:
    """Run inside a worker: report which PDF stacks were imported there."""
    return 'weasyprint' in sys.modules, 'pyhanko' in sys.modules


def _block_until_release(directory: str, label: str) -> str:
    """Run inside a worker: signal start, then wait for the release file."""
    pid = str(os.getpid())
    Path(directory, f'{label}.started').write_text(pid)
    release = Path(directory, 'release')
    deadline = time.monotonic() + 60.0
    while not release.exists():
        if time.monotonic() > deadline:
            raise TimeoutError(f'{label}: release file never appeared')
        time.sleep(0.01)
    return pid


@pytest.fixture
def pool_factory():
    """Create isolated pools that are shut down when the test ends."""
    pools = []

    def factory(
        worker_count: int = 2,
        idle_timeout: float = 60.0,
    ) -> WorkerPool:
        pool = WorkerPool(
            worker_count=worker_count,
            idle_timeout=idle_timeout,
        )
        pools.append(pool)
        return pool

    yield factory

    for pool in pools:
        pool.shutdown()


def test_pool_is_not_created_on_import():
    # given a fresh interpreter importing the application
    code = (
        'import multiprocessing\n'
        'import sys\n'
        'import app.main\n'
        "assert 'weasyprint' not in sys.modules, 'weasyprint imported on import'\n"
        "assert 'pyhanko' not in sys.modules, 'pyhanko imported on import'\n"
        'assert not hasattr(app.main.app.state, "pool"), '
        '"pool manager created on import"\n'
        'assert not multiprocessing.active_children(), '
        '"import spawned processes"\n'
        "print('import-ok')\n"
    )

    # when the modules are imported
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )

    # then no pool exists and neither WeasyPrint nor pyhanko was ever loaded
    assert result.returncode == 0, result.stderr
    assert 'import-ok' in result.stdout


def test_pool_is_not_created_on_startup(client: TestClient):
    # given the application has started up
    manager = app.state.worker_pool

    # then only the cheap manager exists: no pool, no workers, no WeasyPrint
    assert manager.current() is None
    assert not multiprocessing.active_children()
    assert 'weasyprint' not in sys.modules


def test_first_render_creates_the_pool(client: TestClient):
    # given no pool exists yet
    assert current_pool() is None

    # when I send the first render request
    response = _post(client, [('index.html', b'<h1>Hello</h1>')])

    # then the response is a PDF and the pool was created by the request
    assert response.status_code == HTTPStatus.OK
    pool = current_pool()
    assert pool is not None
    assert pool.is_alive
    assert pool.run_id == 1

    # and a worker process (not this one) is now available for jobs
    assert pool.submit(_worker_pid).result(timeout=30) != os.getpid()


def test_worker_count_is_configurable(monkeypatch):
    # given a custom worker count, read when the application starts
    monkeypatch.setenv('WORKER_COUNT', '1')

    with TestClient(app) as client:
        # when I send a render request
        response = _post(client, [('index.html', b'<h1>Hello</h1>')])

        # then a single-worker pool serves it
        assert response.status_code == HTTPStatus.OK
        pool = current_pool()
        assert pool is not None
        assert pool.worker_count == 1
        assert pool.submit(_worker_pid).result(timeout=30) != os.getpid()


def test_first_render_task_runs_in_a_worker_and_the_worker_is_reused(
    tmp_path, pool_factory
):
    # given a fresh single-worker pool and an HTML document
    pool = pool_factory(worker_count=1)
    index = tmp_path / 'index.html'
    index.write_text('<h1>Hello</h1>', encoding='utf-8')
    assert pool.run_id == 0
    assert not multiprocessing.active_children()

    # when the first real render task is submitted
    pdf = pool.submit(_render_pdf, str(index)).result(timeout=30)

    # then the document was actually rendered in a worker process
    assert pdf.startswith(b'%PDF-')

    # and later tasks reuse that same worker process
    pid = pool.submit(_worker_pid).result(timeout=30)
    assert pid != os.getpid()
    for _ in range(3):
        assert pool.submit(_worker_pid).result(timeout=30) == pid


def test_idle_worker_imports_neither_pdf_stack(pool_factory):
    # given a single-worker pool that has only run a trivial job
    pool = pool_factory(worker_count=1)
    pid = pool.submit(_worker_pid).result(timeout=30)
    assert pid != os.getpid()

    # then that worker imported neither the rendering nor the signing stack:
    # each task imports its own dependency lazily, on demand
    weasyprint, pyhanko = pool.submit(_worker_heavy_imports).result(timeout=30)
    assert not weasyprint
    assert not pyhanko


def test_render_worker_does_not_import_the_signing_stack(tmp_path, monkeypatch):
    # given a single-worker pool
    monkeypatch.setenv('WORKER_COUNT', '1')

    with TestClient(app) as client:
        # when a render runs in its worker
        response = _post(client, [('index.html', b'<h1>Hello</h1>')])
        assert response.status_code == HTTPStatus.OK
        pool = current_pool()
        assert pool is not None

        # then WeasyPrint is loaded there while pyhanko stayed out
        weasyprint, pyhanko = pool.submit(_worker_heavy_imports).result(timeout=30)
        assert weasyprint
        assert not pyhanko


def test_signing_worker_does_not_import_the_rendering_stack(monkeypatch):
    # given a single-worker pool
    monkeypatch.setenv('WORKER_COUNT', '1')

    p12 = (Path(__file__).parent / 'samples' / 'sample.p12').read_bytes()
    pdf = (Path(__file__).parent / 'samples' / 'document.pdf').read_bytes()
    signers = '[{"file": "company.p12", "passphrase": "secret"}]'

    with TestClient(app) as client:
        # when a signature is applied in its worker
        response = client.post(
            '/pdf/sign',
            files=[
                ('files', ('document.pdf', pdf)),
                ('files', ('company.p12', p12)),
            ],
            data={'signers': signers},
        )
        assert response.status_code == HTTPStatus.OK
        pool = current_pool()
        assert pool is not None

        # then pyhanko is loaded there while WeasyPrint stayed out
        weasyprint, pyhanko = pool.submit(_worker_heavy_imports).result(timeout=30)
        assert pyhanko
        assert not weasyprint


def test_pool_logs_start_and_shutdown(caplog, pool_factory):
    # given a fresh pool
    caplog.set_level(logging.INFO)
    pool = pool_factory()

    # when the first job starts it
    pool.submit(_worker_pid).result(timeout=30)

    # then the start attempt is logged
    assert 'Creating worker pool with up to 2 worker(s)' in caplog.text

    # when the pool is shut down
    caplog.clear()
    pool.shutdown()

    # then stopping and its completion are both logged
    assert 'Stopping worker pool' in caplog.text
    assert 'Worker pool stopped' in caplog.text


def test_worker_logs_readiness():
    # given a fresh interpreter where a pool runs a single job
    code = (
        'import os\n'
        'from app.logging import configure_logging\n'
        'from app.worker_pool import WorkerPool\n'
        'configure_logging()\n'
        'pool = WorkerPool(worker_count=1)\n'
        'pid = pool.submit(os.getpid).result(timeout=30)\n'
        'print(f"pid={pid}")\n'
        'pool.shutdown()\n'
    )

    # when the modules are imported and the job runs
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )

    # then the pool creation and the worker's own readiness are logged
    assert result.returncode == 0, result.stderr
    pid = next(
        line.split('=', 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith('pid=')
    )
    assert 'Creating worker pool with up to 1 worker(s)' in result.stderr
    assert f'Worker {pid} ready' in result.stderr


def test_application_process_logs_pool_lifecycle_to_stderr():
    # given a fresh interpreter that starts the application and never calls
    # configure_logging itself: the lifespan must configure app logging.
    # This runs in a subprocess because pytest installs root handlers that
    # would mask the production bug of a missing application handler.
    code = (
        'import time\n'
        'from fastapi.testclient import TestClient\n'
        'from app.main import app\n'
        'with TestClient(app) as client:\n'
        '    response = client.post(\n'
        '        "/convert/html",\n'
        '        files={"files": ("index.html", b"<h1>Hello</h1>")},\n'
        '    )\n'
        '    assert response.status_code == 200, response.text\n'
        '    pool = app.state.worker_pool.current()\n'
        '    deadline = time.monotonic() + 30\n'
        '    while pool.is_alive and time.monotonic() < deadline:\n'
        '        time.sleep(0.01)\n'
        'print("done")\n'
    )

    # when the pool is created and then goes idle inside that process
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, 'LOG_LEVEL': 'INFO', 'WORKER_IDLE_TIMEOUT': '0.2'},
        timeout=120,
    )

    # then the parent-process pool logs reach stderr
    assert result.returncode == 0, result.stderr
    assert 'done' in result.stdout
    assert 'Creating worker pool with up to' in result.stderr
    assert 'Worker pool idle for 0.2s: stopping workers' in result.stderr
    assert 'Worker pool stopped after idle timeout' in result.stderr


def test_creating_executor_starts_no_worker(pool_factory):
    # given a pool whose executor has not been created yet
    pool = pool_factory(worker_count=2)

    # when the executor is created without submitting any job
    with pool._lock:
        pool._create_executor_locked()

    # then no worker process is started eagerly
    assert not multiprocessing.active_children()
    assert pool.is_alive
    assert pool.run_id == 1


def test_multiple_renders_reuse_the_same_pool(client: TestClient):
    # given a pool created by the first render
    first = _post(client, [('index.html', b'<h1>Hello</h1>')])
    assert first.status_code == HTTPStatus.OK
    pool = current_pool()
    assert pool is not None
    run_id = pool.run_id

    # when I send more renders
    for _ in range(3):
        response = _post(client, [('index.html', b'<h1>Hello</h1>')])
        assert response.status_code == HTTPStatus.OK

    # then the same pool and workers are reused
    assert current_pool() is pool
    assert pool.run_id == run_id


def test_at_most_two_renders_run_concurrently(tmp_path, pool_factory):
    # given a pool with two workers
    pool = pool_factory()

    # when three renders are submitted
    jobs = [
        pool.submit(_block_until_release, str(tmp_path), f'job{i}') for i in range(3)
    ]

    # then two of them start on the two workers
    wait_until(
        lambda: len(list(tmp_path.glob('*.started'))) == 2,
        timeout=30,
        message='two renders should start concurrently',
    )
    started_pids = {path.read_text() for path in tmp_path.glob('*.started')}
    assert len(started_pids) == 2

    # and the third queues instead of spawning another process
    assert len(list(tmp_path.glob('*.started'))) == 2
    assert pool.run_id == 1

    # when the running renders are released
    (tmp_path / 'release').touch()

    # then the queued render runs as well, on the same pool
    for job in jobs:
        assert job.result(timeout=30)
    assert len(list(tmp_path.glob('*.started'))) == 3
    assert pool.run_id == 1


def test_active_jobs_tracks_running_work(tmp_path, pool_factory):
    # given an idle pool
    pool = pool_factory(worker_count=1, idle_timeout=30)

    # when a render is running
    job = pool.submit(_block_until_release, str(tmp_path), 'render')
    wait_until(
        lambda: pool.active_jobs == 1,
        message='the render should be tracked as active',
    )

    # then releasing it drives the activity counter back to zero
    (tmp_path / 'release').touch()
    assert job.result(timeout=30)
    wait_until(lambda: pool.active_jobs == 0, message='pool should be idle')


def test_pool_shuts_down_after_idle_timeout(monkeypatch):
    # given a short idle timeout, read when the application starts
    monkeypatch.setenv('WORKER_IDLE_TIMEOUT', '0.5')

    with TestClient(app) as client:
        # when a render has finished
        response = _post(client, [('index.html', b'<h1>Hello</h1>')])
        assert response.status_code == HTTPStatus.OK
        pool = current_pool()
        assert pool is not None
        assert pool.is_alive
        assert pool.worker_count == 2
        assert pool.run_id == 1

        # and a worker has been started by that render
        pid = pool.submit(_worker_pid).result(timeout=30)
        assert pid != os.getpid()
        assert _process_is_alive(pid)

        # then the pool winds down once the idle timeout expires
        wait_until(
            lambda: not pool.is_alive,
            message='pool should stop after the idle timeout',
        )
        assert pool.idle_timeouts_fired >= 1
        assert pool.run_id == 1

        # and the worker process is gone
        wait_until(
            lambda: not _process_is_alive(pid),
            message='the worker should exit after the idle timeout',
        )


def test_idle_shutdown_logs_completion(caplog, pool_factory):
    # given a fresh pool with a short idle timeout
    caplog.set_level(logging.INFO)
    pool = pool_factory(worker_count=1, idle_timeout=0.2)

    # when a job runs and the pool goes idle
    pool.submit(_worker_pid).result(timeout=30)
    wait_until(
        lambda: not pool.is_alive,
        timeout=30,
        message='pool should stop after the idle timeout',
    )

    # then the idle shutdown reports both its start and its completion
    assert 'Worker pool idle for 0.2s: stopping workers' in caplog.text
    assert 'Worker pool stopped after idle timeout' in caplog.text


def test_render_after_idle_shutdown_recreates_the_pool(monkeypatch):
    # given a pool that already shut down after inactivity
    monkeypatch.setenv('WORKER_IDLE_TIMEOUT', '0.5')

    with TestClient(app) as client:
        response = _post(client, [('index.html', b'<h1>Hello</h1>')])
        assert response.status_code == HTTPStatus.OK
        pool = current_pool()
        assert pool is not None
        first_run = pool.run_id
        wait_until(
            lambda: not pool.is_alive,
            message='pool should stop while idle',
        )

        # when a new render request arrives
        response = _post(client, [('index.html', b'<h1>Hello</h1>')])

        # then a fresh pool serves it transparently
        assert response.status_code == HTTPStatus.OK
        assert current_pool() is pool
        assert pool.is_alive
        assert pool.run_id == first_run + 1
        assert pool.submit(_worker_pid).result(timeout=30) != os.getpid()


def test_idle_shutdown_never_interrupts_an_active_render(
    tmp_path,
    pool_factory,
):
    # given a pool with an idle timeout shorter than a render
    pool = pool_factory(worker_count=2, idle_timeout=0.2)
    pool.submit(_worker_pid).result(timeout=30)

    # and a render that is running
    job = pool.submit(_block_until_release, str(tmp_path), 'render')
    wait_until(
        lambda: (tmp_path / 'render.started').exists(),
        timeout=30,
        message='render should start',
    )
    wait_until(
        lambda: pool.active_jobs == 1,
        message='the render should be tracked as active',
    )

    # when the idle timer expires while the render is still active
    pool._on_idle_timeout(pool._epoch)

    # then the pool is not shut down
    assert pool.is_alive
    assert pool.active_jobs == 1

    # when the render finishes
    (tmp_path / 'release').touch()
    assert job.result(timeout=30)

    # then the pool winds down normally
    wait_until(lambda: not pool.is_alive, message='pool should stop when idle')


def test_application_shutdown_closes_the_pool():
    # given an application serving renders
    with TestClient(app) as test_client:
        response = _post(test_client, [('index.html', b'<h1>Hello</h1>')])
        assert response.status_code == HTTPStatus.OK
        pool = current_pool()
        assert pool is not None
        assert pool.is_alive
        pid = pool.submit(_worker_pid).result(timeout=30)
        assert pid != os.getpid()

    # when the application shuts down
    # then the pool is gone and no worker process is left behind
    assert current_pool() is None
    assert not pool.is_alive
    wait_until(
        lambda: not _process_is_alive(pid),
        message='worker processes should be reaped on shutdown',
    )
    with pytest.raises(RuntimeError, match='shut down'):
        pool.submit(_worker_pid)

    # and shutting the pool down again is a no-op
    pool.shutdown()


def test_render_error_is_mapped_to_a_400(client: TestClient):
    # given a document referencing a missing asset
    files = [('index.html', b'<img src="missing.png">')]

    # when I send it for rendering
    response = _post(client, files)

    # then the worker-side error is mapped to the existing client error
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert 'Failed to load a resource' in response.json()['error']

    # and WeasyPrint stayed inside the worker process
    assert 'weasyprint' not in sys.modules


def test_worker_exception_propagates_to_the_caller(pool_factory):
    # given a running pool
    pool = pool_factory()

    # when a worker job fails unexpectedly
    # then the failure reaches the caller as a plain exception,
    # which the route maps to the generic 500 response
    with pytest.raises(ValueError, match='worker-side failure'):
        pool.submit(_raise_worker_error).result(timeout=30)

    # and the pool keeps serving renders
    assert pool.submit(_worker_pid).result(timeout=30) != os.getpid()


def test_pool_manager_creates_the_pool_lazily():
    # given a fresh manager
    manager = WorkerPoolManager(2, 60.0)
    assert manager.current() is None

    # when the pool is first requested
    pool = manager.get()

    # then it is created once and reused afterwards
    assert manager.current() is pool
    assert manager.get() is pool

    # and shutting the manager down removes the pool for good
    manager.shutdown()
    assert manager.current() is None
    with pytest.raises(RuntimeError, match='shut down'):
        manager.get()
    manager.shutdown()  # idempotent


def test_submit_replaces_a_broken_pool(pool_factory, monkeypatch):
    # given a running pool
    pool = pool_factory()
    pool.submit(_worker_pid).result(timeout=30)
    first_run = pool.run_id

    # and an executor whose workers just died
    executor = pool._executor

    def broken_submit(fn, *args, **kwargs):
        raise BrokenProcessPool('simulated worker crash')

    monkeypatch.setattr(executor, 'submit', broken_submit)

    # when a new job is submitted
    pid = pool.submit(_worker_pid).result(timeout=30)

    # then the broken pool is replaced by a fresh one
    assert pool.run_id == first_run + 1
    assert pool.is_alive
    assert pid != os.getpid()
    wait_until(lambda: pool.active_jobs == 0, message='pool should be idle')


def test_first_sign_task_runs_in_a_worker(pool_factory):
    # given a fresh single-worker pool and a real signing request
    p12 = (Path(__file__).parent / 'samples' / 'sample.p12').read_bytes()
    pdf = (Path(__file__).parent / 'samples' / 'document.pdf').read_bytes()
    pool = pool_factory(worker_count=1)
    assert pool.run_id == 0

    # when the first real signing task is submitted
    signed = pool.submit(
        _apply_signatures,
        pdf,
        [('company.p12', p12, 'secret')],
    ).result(timeout=30)

    # then the document was actually signed in a worker process
    assert signed.startswith(b'%PDF-')
    assert len(signed) > len(pdf)

    # and the worker serving it is not this process
    assert pool.submit(_worker_pid).result(timeout=30) != os.getpid()


def test_submit_failure_does_not_leak_active_jobs(pool_factory, monkeypatch):
    # given a pool whose executor always refuses jobs
    pool = pool_factory()

    def broken_submit(fn, *args, **kwargs):
        raise BrokenProcessPool('simulated worker crash')

    monkeypatch.setattr(ProcessPoolExecutor, 'submit', broken_submit)

    # when a job is submitted
    # then the failure propagates to the caller
    with pytest.raises(BrokenProcessPool):
        pool.submit(_worker_pid)

    # and no activity is leaked, which would block idle shutdown forever
    assert pool.active_jobs == 0
    assert not pool.is_alive


def test_wait_until_fails_instead_of_hanging():
    with pytest.raises(AssertionError, match='never true'):
        wait_until(lambda: False, timeout=0.05, message='never true')


def test_pool_rejects_invalid_configuration():
    with pytest.raises(ValueError):
        WorkerPool(worker_count=0)
    with pytest.raises(ValueError):
        WorkerPool(idle_timeout=0)
    with pytest.raises(ValueError):
        WorkerPoolManager(worker_count=0, idle_timeout=60)
    with pytest.raises(ValueError):
        WorkerPoolManager(worker_count=2, idle_timeout=0)
