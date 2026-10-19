"""HTTP Basic password protection for the UI and its API.

The browser shows its own login prompt on the first visit and then sends the
credentials automatically with every request to the same site.
"""
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app import config

# HTTPBasic() reads the "Authorization: Basic ..." header. If it's missing,
# FastAPI answers 401 with "WWW-Authenticate: Basic", which triggers the prompt.
security = HTTPBasic()


def require_login(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    # secrets.compare_digest takes the same time whether the first or the last
    # character is wrong, so attackers can't guess the password from timing.
    user_ok = secrets.compare_digest(credentials.username.encode(), config.APP_USERNAME.encode())
    pass_ok = bool(config.APP_PASSWORD) and secrets.compare_digest(
        credentials.password.encode(), config.APP_PASSWORD.encode()
    )
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
