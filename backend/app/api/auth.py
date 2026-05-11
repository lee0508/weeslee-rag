# Admin 인증 엔드포인트 — 로그인(토큰 발급) 및 토큰 검증
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel

from app.core.auth import create_access_token, decode_token, require_admin_token
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class VerifyResponse(BaseModel):
    valid: bool
    username: str


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    if req.username != settings.admin_username or req.password != settings.admin_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )
    token = create_access_token(req.username)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_hours * 3600,
    )


@router.get("/verify", response_model=VerifyResponse)
async def verify(username: str = Depends(require_admin_token)):
    return VerifyResponse(valid=True, username=username)
