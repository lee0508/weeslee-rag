# 사용자 인증 엔드포인트 — 공용 접속코드 방식 (Phase A)
import os
import time
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String, func
from sqlalchemy.orm import Session

from app.core.database import Base, engine, get_db

# .env 로드 (프로젝트 루트 기준)
_env_path = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_env_path)

router = APIRouter(prefix="/auth", tags=["User Auth"])

# 환경변수에서 설정 로드
CODE_HASH = os.getenv("USER_ACCESS_CODE_HASH", "")
SECRET = os.getenv("USER_TOKEN_SECRET", "")
TTL_DAYS = int(os.getenv("USER_TOKEN_TTL_DAYS", "30"))

# IP 실패 카운터: {ip: (fail_count, blocked_until_epoch)}
_fails: dict[str, tuple[int, float]] = {}
MAX_FAILS, BLOCK_SEC = 5, 600


class AccessAccount(Base):
    __tablename__ = "user_access_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String(36), nullable=False, unique=True, index=True)
    display_name = Column(String(50), nullable=False, unique=True, index=True)
    code_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=func.now())
    last_login_at = Column(DateTime, default=func.now(), onupdate=func.now())


class AccessBody(BaseModel):
    code: str
    display_name: str = ""


class AccessResponse(BaseModel):
    token: str
    client_id: str
    display_name: str
    expires_at: int


class RegisterBody(BaseModel):
    code: str
    display_name: str


class RegisterResponse(BaseModel):
    ok: bool
    client_id: str
    display_name: str


class VerifyResponse(BaseModel):
    ok: bool
    client_id: str
    display_name: str


def init_user_auth_tables():
    """사용자 등록 계정 테이블 생성"""
    try:
        Base.metadata.create_all(bind=engine, tables=[AccessAccount.__table__])
    except Exception as exc:
        print(f"사용자 인증 테이블 생성 오류 (이미 존재할 수 있음): {exc}")


def _issue_token(client_id: str, name: str) -> AccessResponse:
    exp = int(time.time()) + TTL_DAYS * 86400
    token = jwt.encode(
        {"client_id": client_id, "name": name, "exp": exp},
        SECRET,
        algorithm="HS256"
    )
    return AccessResponse(
        token=token,
        client_id=client_id,
        display_name=name,
        expires_at=exp
    )


def _normalize_display_name(value: str) -> str:
    return (value or "").strip()[:20]


@router.post("/register", response_model=RegisterResponse)
async def register_access_account(
    body: RegisterBody,
    db: Session = Depends(get_db)
):
    """사용자별 접속 코드 등록"""
    name = _normalize_display_name(body.display_name)
    code = (body.code or "").strip()

    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="표시 이름을 입력해 주세요"
        )
    if len(code) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="접속코드는 4자 이상 입력해 주세요"
        )

    existing = db.query(AccessAccount).filter(
        AccessAccount.display_name == name
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 등록된 표시 이름입니다"
        )

    account = AccessAccount(
        client_id=str(uuid.uuid4()),
        display_name=name,
        code_hash=bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode(),
    )
    db.add(account)
    db.commit()

    return RegisterResponse(
        ok=True,
        client_id=account.client_id,
        display_name=account.display_name,
    )


@router.post("/access", response_model=AccessResponse)
async def access(
    body: AccessBody,
    request: Request,
    db: Session = Depends(get_db)
):
    """등록 계정 또는 공용 접속코드로 인증하여 토큰 발급"""
    ip = request.client.host if request.client else "unknown"
    cnt, until = _fails.get(ip, (0, 0.0))

    # 차단 중인지 확인
    if time.time() < until:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="시도 횟수를 초과했습니다. 10분 후 다시 시도하세요"
        )

    # 서버 설정 누락 방어
    if not SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="인증 설정이 준비되지 않았습니다"
        )

    # 표시 이름 정리 (1~20자, 비면 익명)
    name = _normalize_display_name(body.display_name) or "익명"

    # 등록 사용자 우선 확인: 표시 이름이 있으면 그 계정의 코드만 허용
    account = db.query(AccessAccount).filter(
        AccessAccount.display_name == name
    ).first()
    if account:
        if not bcrypt.checkpw(body.code.encode(), account.code_hash.encode()):
            cnt += 1
            _fails[ip] = (cnt, time.time() + BLOCK_SEC if cnt >= MAX_FAILS else 0.0)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="표시 이름 또는 접속코드가 올바르지 않습니다"
            )

        _fails.pop(ip, None)
        account.last_login_at = datetime.utcnow()
        db.commit()
        return _issue_token(account.client_id, account.display_name)

    if not CODE_HASH:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="공용 접속코드가 준비되지 않았습니다"
        )

    # 공용 코드 검증 (bcrypt)
    if not bcrypt.checkpw(body.code.encode(), CODE_HASH.encode()):
        cnt += 1
        _fails[ip] = (cnt, time.time() + BLOCK_SEC if cnt >= MAX_FAILS else 0.0)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="접속코드가 올바르지 않습니다"
        )

    # 성공 → 카운터 초기화
    _fails.pop(ip, None)
    return _issue_token(str(uuid.uuid4()), name)


# 검증 의존성: 사용자 API 전체에서 재사용
_bearer = HTTPBearer(auto_error=False)


def verify_user(cred: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    """Bearer 토큰 검증 → {client_id, name} 반환. 실패는 모두 401."""
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다"
        )
    if not SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="인증 설정이 준비되지 않았습니다"
        )
    try:
        payload = jwt.decode(cred.credentials, SECRET, algorithms=["HS256"])
        return {
            "client_id": payload["client_id"],
            "name": payload.get("name", "익명")
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰이 만료되었습니다"
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰이 유효하지 않습니다"
        )


def verify_user_optional(cred: HTTPAuthorizationCredentials = Depends(_bearer)) -> Optional[dict]:
    """토큰이 있으면 검증, 없으면 None 반환 (관리자/사용자 겸용 API 용)"""
    if cred is None:
        return None
    if not SECRET:
        return None
    try:
        payload = jwt.decode(cred.credentials, SECRET, algorithms=["HS256"])
        return {
            "client_id": payload["client_id"],
            "name": payload.get("name", "익명")
        }
    except Exception:
        return None


@router.get("/verify", response_model=VerifyResponse)
async def verify(user: dict = Depends(verify_user)):
    """토큰 검증 엔드포인트"""
    return VerifyResponse(
        ok=True,
        client_id=user["client_id"],
        display_name=user["name"]
    )
