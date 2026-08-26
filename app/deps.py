import hmac
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(auto_error=False)


def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid API key.',
        )
