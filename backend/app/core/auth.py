# Admin JWT 인증 유틸리티 및 FastAPI 의존성 함수
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    """토큰 검증 후 username 반환. 유효하지 않으면 None."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def require_admin_token(token: Optional[str] = Depends(oauth2_scheme)) -> str:
    """인증된 Admin 토큰이 없으면 HTTP 401 반환하는 FastAPI 의존성."""
    # [DEV MODE] 개발/시연 모드에서는 인증 우회
    if settings.debug and settings.app_env == "development":
        return "dev-user"

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 토큰이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = decode_token(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않거나 만료된 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


def optional_admin_token(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[str]:
    """선택적 인증 - 토큰이 있으면 검증하고, 없어도 통과 (읽기 전용 공개 엔드포인트용)."""
    if not token:
        return None
    username = decode_token(token)
    return username  # None일 수도 있음 (잘못된 토큰)
