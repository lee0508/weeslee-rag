# 대화 세션 저장/복원 + 사용 로그 (Phase B/D)
import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Text, DateTime, func, text
from sqlalchemy.orm import Session

from app.core.database import Base, get_db, engine
from app.api.user_auth import verify_user

router = APIRouter(prefix="/chat", tags=["Chat Sessions"])


# ============================================================
# SQLAlchemy 모델 정의
# ============================================================
class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id = Column(String(36), primary_key=True)
    client_id = Column(String(36), nullable=False, index=True)
    display_name = Column(String(50), default="")
    title = Column(String(100), default="")
    source_id = Column(String(100), default="")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), nullable=False, index=True)
    turn_no = Column(Integer, nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, default="")
    docs_json = Column(Text, default="[]")
    terms_json = Column(Text, default="[]")
    hints_json = Column(Text, default="{}")
    elapsed_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String(36))
    display_name = Column(String(50))
    question = Column(Text)
    source_id = Column(String(100))
    result_count = Column(Integer)
    answered = Column(Integer)  # 0/1
    elapsed_ms = Column(Integer)
    created_at = Column(DateTime, default=func.now())


# 테이블 생성 (앱 시작 시)
def init_chat_tables():
    """채팅 관련 테이블 생성"""
    try:
        Base.metadata.create_all(bind=engine, tables=[
            ChatSession.__table__,
            ChatMessage.__table__,
            QueryLog.__table__
        ])
    except Exception as e:
        print(f"채팅 테이블 생성 오류 (이미 존재할 수 있음): {e}")


# ============================================================
# Pydantic 모델
# ============================================================
class NewSessionBody(BaseModel):
    source_id: str = ""


class SessionResponse(BaseModel):
    session_id: str


class TurnBody(BaseModel):
    turn_no: int
    question: str
    answer: str = ""
    docs: List[dict] = []
    terms: List[str] = []
    hints: dict = {}
    elapsed_ms: int = 0


class TurnResponse(BaseModel):
    ok: bool
    turn_no: int


class TitleBody(BaseModel):
    title: str


class OkResponse(BaseModel):
    ok: bool


# ============================================================
# API 엔드포인트
# ============================================================
@router.get("/sessions")
async def list_sessions(
    scope: str = "mine",
    user: dict = Depends(verify_user),
    db: Session = Depends(get_db)
):
    """세션 목록 조회 — scope=mine(기본): 내 것만 / scope=all: 전사 전체"""
    try:
        if scope == "all":
            # 전사 전체 (작성자 이름 포함)
            sessions = db.query(ChatSession).order_by(
                ChatSession.updated_at.desc()
            ).limit(50).all()
        else:
            # 내 것만 (기본)
            sessions = db.query(ChatSession).filter(
                ChatSession.client_id == user["client_id"]
            ).order_by(ChatSession.updated_at.desc()).limit(50).all()

        result = []
        for s in sessions:
            # 턴 수 계산
            turn_count = db.query(ChatMessage).filter(
                ChatMessage.session_id == s.session_id
            ).count()

            result.append({
                "session_id": s.session_id,
                "client_id": s.client_id,
                "display_name": s.display_name or "",
                "title": s.title or "새 대화",
                "source_id": s.source_id or "",
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "turn_count": turn_count,
                "is_mine": s.client_id == user["client_id"]
            })

        return {"sessions": result}
    except Exception as e:
        print(f"세션 목록 조회 오류: {e}")
        return {"sessions": []}


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    body: NewSessionBody,
    user: dict = Depends(verify_user),
    db: Session = Depends(get_db)
):
    """새 세션 생성"""
    session_id = str(uuid.uuid4())
    session = ChatSession(
        session_id=session_id,
        client_id=user["client_id"],
        display_name=user["name"],
        source_id=body.source_id or ""
    )
    db.add(session)
    db.commit()
    return SessionResponse(session_id=session_id)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: dict = Depends(verify_user),
    db: Session = Depends(get_db)
):
    """세션 상세 조회 (전사 공유: 누구나 열람 가능)"""
    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="세션을 찾을 수 없습니다"
        )

    # 메시지 조회
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.turn_no).all()

    msg_list = []
    for m in messages:
        msg_list.append({
            "turn_no": m.turn_no,
            "question": m.question,
            "answer": m.answer or "",
            "docs": json.loads(m.docs_json or "[]"),
            "terms": json.loads(m.terms_json or "[]"),
            "hints": json.loads(m.hints_json or "{}"),
            "elapsed_ms": m.elapsed_ms or 0,
            "created_at": m.created_at.isoformat() if m.created_at else None
        })

    return {
        "session": {
            "session_id": session.session_id,
            "client_id": session.client_id,
            "display_name": session.display_name or "",
            "title": session.title or "",
            "source_id": session.source_id or "",
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None
        },
        "is_mine": session.client_id == user["client_id"],
        "messages": msg_list
    }


@router.post("/sessions/{session_id}/messages", response_model=TurnResponse)
async def save_turn(
    session_id: str,
    body: TurnBody,
    user: dict = Depends(verify_user),
    db: Session = Depends(get_db)
):
    """턴 저장 (소유자만)"""
    # 세션 조회 및 소유권 확인
    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="세션을 찾을 수 없습니다"
        )

    if session.client_id != user["client_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 대화만 수정할 수 있습니다"
        )

    # 문서 최대 10개 제한
    docs = body.docs[:10] if body.docs else []

    # 메시지 저장
    message = ChatMessage(
        session_id=session_id,
        turn_no=body.turn_no,
        question=body.question,
        answer=body.answer or "",
        docs_json=json.dumps(docs, ensure_ascii=False),
        terms_json=json.dumps(body.terms or [], ensure_ascii=False),
        hints_json=json.dumps(body.hints or {}, ensure_ascii=False),
        elapsed_ms=body.elapsed_ms or 0
    )
    db.add(message)

    # 첫 턴이면 제목 자동 설정
    if body.turn_no == 0:
        session.title = body.question[:40]

    # updated_at 갱신
    session.updated_at = datetime.now()
    db.commit()

    # 사용 로그 기록 (Phase D)
    log = QueryLog(
        client_id=user["client_id"],
        display_name=user["name"],
        question=body.question,
        source_id=session.source_id or "",
        result_count=len(docs),
        answered=1 if body.answer else 0,
        elapsed_ms=body.elapsed_ms or 0
    )
    db.add(log)
    db.commit()

    return TurnResponse(ok=True, turn_no=body.turn_no)


@router.put("/sessions/{session_id}", response_model=OkResponse)
async def rename_session(
    session_id: str,
    body: TitleBody,
    user: dict = Depends(verify_user),
    db: Session = Depends(get_db)
):
    """제목 수정 (소유자만)"""
    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="세션을 찾을 수 없습니다"
        )

    if session.client_id != user["client_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 대화만 수정할 수 있습니다"
        )

    session.title = (body.title or "").strip()[:60]
    db.commit()
    return OkResponse(ok=True)


@router.delete("/sessions/{session_id}", response_model=OkResponse)
async def delete_session(
    session_id: str,
    user: dict = Depends(verify_user),
    db: Session = Depends(get_db)
):
    """세션 삭제 (소유자만)"""
    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="세션을 찾을 수 없습니다"
        )

    if session.client_id != user["client_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 대화만 삭제할 수 있습니다"
        )

    # 메시지 먼저 삭제
    db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).delete()

    # 세션 삭제
    db.delete(session)
    db.commit()
    return OkResponse(ok=True)
