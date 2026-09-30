"""Lazily-started, self-recycling pool of worker processes.

Worker processes are created on demand by a :class:`ProcessPoolExecutor`
when the first jobs are submitted, reused for every subsequent job, and
stopped after a configurable period without activity so the operating
system can reclaim their memory; a later submission transparently creates
a fresh pool.

The pool is deliberately ignorant of what its workers do. Its initializer
only configures worker logging; each task imports its own dependencies
inside the worker on its first actual job (``_render_pdf`` imports
WeasyPrint, ``_apply_signature`` imports pyhanko), so those libraries are
only ever imported in the worker processes that need them and never in the
parent process.

Worker creation is delegated to the executor: the first concurrent jobs
spawn the workers one by one, up to ``worker_count``.

The shared pool is owned by a :class:`WorkerPoolManager` attached to
``app.state`` (wired up by the application lifespan and injected into
routes), so no module-level singleton is involved.
"""

import logging
import multiprocessing
import os
import threading
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from .logging import configure_logging

logger = logging.getLogger(__name__)


def _validate(worker_count: int, idle_timeout: float) -> None:
    """Reject invalid pool configuration."""
    if worker_count < 1:
        raise ValueError('worker_count must be >= 1')

    if idle_timeout <= 0:
        raise ValueError('idle_timeout must be > 0')


def _init_worker() -> None:
    """Initialize a worker process (executor initializer).

    Runs inside each worker before any job is dispatched to it and does
    nothing but configure logging: the task entry points import their own
    dependencies on demand. A failure here aborts the worker, which makes
    the executor fail the pending future with :class:`BrokenProcessPool`,
    so a job can never run on a worker that did not finish initialization.
    """
    configure_logging()
    logger.info('Worker %d ready', os.getpid())


def _stop_executor(executor: ProcessPoolExecutor, *, wait: bool) -> None:
    """Shut an executor down."""
    executor.shutdown(wait=wait)


class WorkerPool:
    """A lazily-started, self-recycling pool of worker processes.

    Worker processes are created on demand by the executor when the first
    jobs are submitted, initialized by :func:`_init_worker` (logging only)
    and reused for every subsequent job. Once the pool has been idle for
    ``idle_timeout`` seconds with no active or queued jobs, the workers are
    shut down; the next submission transparently creates a fresh pool.

    ``submit``/idle-shutdown races are serialized with a lock and an
    activity counter, so the pool is never torn down while a job is running
    or queued, and a submission never lands on a shut-down executor.
    """

    def __init__(
        self,
        worker_count: int = 2,
        idle_timeout: float = 60.0,
    ) -> None:
        _validate(worker_count, idle_timeout)

        self._worker_count = worker_count
        self._idle_timeout = idle_timeout
        self._lock = threading.Lock()
        self._executor: ProcessPoolExecutor | None = None
        self._active_jobs = 0
        self._run_id = 0
        self._epoch = 0
        self._timer: threading.Timer | None = None
        self._idle_timeouts_fired = 0
        self._closed = False

    @property
    def worker_count(self) -> int:
        """Maximum number of worker processes."""
        return self._worker_count

    @property
    def is_alive(self) -> bool:
        """Whether the pool exists (workers may be created on demand)."""
        with self._lock:
            return self._executor is not None

    @property
    def run_id(self) -> int:
        """How many times the pool has been created; 0 until first use."""
        with self._lock:
            return self._run_id

    @property
    def active_jobs(self) -> int:
        """Number of queued or running jobs (0 when the pool is idle)."""
        with self._lock:
            return self._active_jobs

    @property
    def idle_timeouts_fired(self) -> int:
        """How often the idle timer has expired since pool creation."""
        with self._lock:
            return self._idle_timeouts_fired

    def submit(self, fn: Callable[..., object], /, *args: object) -> Future:
        """Run ``fn(*args)`` in a worker process and return its future.

        Creates the pool on first use; the executor spawns the worker
        processes on demand. The job counts as activity from submission
        until its future completes, so idle shutdown never races with queued
        or running work.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError('Worker pool has been shut down')
            self._cancel_timer_locked()

            executor = self._executor
            if executor is None:
                executor = self._create_executor_locked()

            self._active_jobs += 1
            try:
                try:
                    future = executor.submit(fn, *args)
                except BrokenProcessPool:
                    # A worker died unexpectedly: replace the broken pool
                    # and retry once. ``wait=False`` keeps job callbacks
                    # (which need this lock) from deadlocking.
                    logger.warning('Worker process died; recreating the worker pool')
                    self._dispose_locked(wait=False)
                    executor = self._create_executor_locked()
                    try:
                        future = executor.submit(fn, *args)
                    except BaseException:
                        # The fresh pool cannot accept jobs either: tear it
                        # down so no dead executor is left behind.
                        self._dispose_locked(wait=False)
                        raise
            except BaseException:
                self._active_jobs -= 1
                raise

        future.add_done_callback(self._job_finished)

        return future

    def shutdown(self) -> None:
        """Stop the workers and close the pool. Idempotent."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cancel_timer_locked()
            executor = self._detach_locked()

        if executor is None:
            logger.debug('Worker pool closed (no running workers)')
            return

        # Wait outside the lock: in-flight job callbacks need it.
        logger.info('Stopping worker pool')
        _stop_executor(executor, wait=True)
        logger.info('Worker pool stopped')

    def _create_executor_locked(self) -> ProcessPoolExecutor:
        """Create a new pool. Caller must hold the lock.

        No worker is started here: the executor spawns them on demand as
        jobs are submitted, and each new worker runs :func:`_init_worker`
        before it accepts its first job.
        """
        logger.info('Creating worker pool with up to %d worker(s)', self._worker_count)

        context = multiprocessing.get_context('spawn')
        executor = ProcessPoolExecutor(
            max_workers=self._worker_count,
            mp_context=context,
            initializer=_init_worker,
        )

        self._executor = executor
        self._run_id += 1
        return executor

    def _detach_locked(self) -> ProcessPoolExecutor | None:
        """Forget the current executor. Caller must hold the lock."""
        executor, self._executor = self._executor, None
        return executor

    def _dispose_locked(self, *, wait: bool) -> None:
        """Stop the current executor. Caller must hold the lock.

        With ``wait=False`` this never joins the executor's manager thread,
        so job callbacks blocked on this lock cannot deadlock against it.
        """
        executor = self._detach_locked()
        if executor is not None:
            _stop_executor(executor, wait=wait)

    def _cancel_timer_locked(self) -> None:
        """Invalidate scheduled idle shutdowns. Caller must hold the lock."""
        self._epoch += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _schedule_idle_shutdown_locked(self) -> None:
        """Arm the idle timer. Caller must hold the lock."""
        self._cancel_timer_locked()
        timer = threading.Timer(
            self._idle_timeout,
            self._on_idle_timeout,
            args=(self._epoch,),
        )
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _on_idle_timeout(self, epoch: int) -> None:
        """Shut the workers down if still idle when the timer expires."""
        with self._lock:
            self._idle_timeouts_fired += 1
            if self._closed or epoch != self._epoch or self._active_jobs > 0:
                return

            executor = self._detach_locked()
            if executor is None:
                return

            # The activity counter is zero and the lock is held, so no job
            # is running or queued and no submission can arrive: it is safe
            # to join the workers here.
            logger.info(
                'Worker pool idle for %.1fs: stopping workers',
                self._idle_timeout,
            )
            _stop_executor(executor, wait=True)
            logger.info('Worker pool stopped after idle timeout')
            self._timer = None

    def _job_finished(self, future: Future) -> None:
        """Bookkeep a completed job and arm the idle timer when done."""
        with self._lock:
            self._active_jobs -= 1
            if (
                self._active_jobs == 0
                and not self._closed
                and self._executor is not None
            ):
                self._schedule_idle_shutdown_locked()


class WorkerPoolManager:
    """Lazily creates and owns the application's shared worker pool.

    A manager is cheap to build and starts no processes; one instance
    lives on ``app.state`` so the application — not a module global —
    owns the pool. Configuration is validated when the manager is built,
    the pool object is created on the first request that needs it, and
    worker processes only start with that pool's first job.
    """

    def __init__(
        self,
        worker_count: int,
        idle_timeout: float,
    ) -> None:
        _validate(worker_count, idle_timeout)

        self._worker_count = worker_count
        self._idle_timeout = idle_timeout
        self._lock = threading.Lock()
        self._pool: WorkerPool | None = None
        self._closed = False

    def get(self) -> WorkerPool:
        """Return the shared pool, creating it on first use."""
        with self._lock:
            if self._closed:
                raise RuntimeError('Worker pool manager has been shut down')

            if self._pool is None:
                self._pool = WorkerPool(
                    self._worker_count,
                    self._idle_timeout,
                )

            return self._pool

    def current(self) -> WorkerPool | None:
        """Return the pool if it was created already, else ``None``."""
        with self._lock:
            return self._pool

    def shutdown(self) -> None:
        """Shut the pool down if it exists. Safe to call repeatedly."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown()
