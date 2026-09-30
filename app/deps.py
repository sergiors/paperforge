import hmac
import logging
import os
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .worker_pool import WorkerPool

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


def get_worker_pool(request: Request) -> WorkerPool:
    """Provide the application's shared worker pool.

    The pool object is created lazily, on the first request that needs it,
    by the manager on ``app.state``; worker processes only start with the
    pool's first job.
    """
    return request.app.state.worker_pool.get()


def verify_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> None:
    """Require a valid API key when the ``API_KEY`` environment variable is set.

    When ``API_KEY`` is unset or empty, authentication is disabled and every
    request is allowed. Otherwise, the request must include a matching bearer
    token in the ``Authorization`` header.
    """
    api_key = os.environ.get('API_KEY', '')

    if not api_key:
        return

    if credentials is None or not hmac.compare_digest(credentials.credentials, api_key):
        logger.warning('Authentication failed: missing or invalid API key')
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid API key.',
        )
