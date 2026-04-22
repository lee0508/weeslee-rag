# PromptoRAG 로컬 개발 환경 구축 가이드

**작성일:** 2026-04-22
**환경:** Windows 10

---

## 1. Python 가상환경 설정

### 1.1 가상환경 생성

```powershell
# 프로젝트 폴더로 이동
cd C:\xampp\htdocs\weeslee-rag

# 가상환경 생성
python -m venv venv

# 가상환경 활성화 (PowerShell)
.\venv\Scripts\Activate.ps1

# 가상환경 활성화 (CMD)
.\venv\Scripts\activate.bat
```

### 1.2 의존성 패키지 설치

```powershell
# pip 업그레이드
python -m pip install --upgrade pip

# 의존성 설치
pip install -r backend\requirements.txt
```

---

## 2. MySQL 데이터베이스 설정

### 2.1 데이터베이스 생성

MySQL에 접속하여 실행:

```sql
-- 데이터베이스 생성
CREATE DATABASE IF NOT EXISTS promptorag
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

-- 사용자 생성 (필요시)
-- CREATE USER 'promptorag'@'localhost' IDENTIFIED BY 'your_password';
-- GRANT ALL PRIVILEGES ON promptorag.* TO 'promptorag'@'localhost';
-- FLUSH PRIVILEGES;

-- 확인
SHOW DATABASES;
USE promptorag;
```

### 2.2 초기 데이터 삽입 (선택)

```sql
-- 기본 컬렉션 생성
INSERT INTO collections (name, description, is_system) VALUES
('all_documents', '전체 문서 저장소', TRUE),
('ISP', 'ISP(정보화전략계획) 관련 문서', FALSE),
('ISMP', 'ISMP(정보시스템마스터플랜) 관련 문서', FALSE),
('ODA', 'ODA 제안서 및 보고서', FALSE),
('policy', '정책연구 문서', FALSE);
```

---

## 3. Ollama 설정

### 3.1 Ollama 실행 확인

```powershell
# Ollama 버전 확인
ollama --version

# Ollama 서비스 시작 (백그라운드)
ollama serve
```

### 3.2 모델 다운로드

```powershell
# LLM 모델 다운로드
ollama pull llama3:8b

# 임베딩 모델 다운로드
ollama pull nomic-embed-text

# 설치된 모델 확인
ollama list
```

### 3.3 연결 테스트

```powershell
# API 테스트
curl http://localhost:11434/api/tags
```

---

## 4. ChromaDB 설정

ChromaDB는 Python 패키지로 설치되며, 별도 서버 실행이 필요 없습니다.
`./chroma_data` 폴더에 데이터가 저장됩니다.

---

## 5. 환경 변수 설정

### 5.1 .env 파일 확인

```powershell
# .env 파일이 있는지 확인
dir .env

# 없으면 .env.example 복사
copy .env.example .env
```

### 5.2 .env 파일 수정

```env
# Database (MySQL)
DB_HOST=localhost
DB_PORT=3306
DB_NAME=promptorag
DB_USER=root
DB_PASSWORD=        # MySQL root 비밀번호 입력

# Ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3:8b
OLLAMA_EMBED_MODEL=nomic-embed-text
```

---

## 6. 서버 실행

### 6.1 개발 서버 실행

```powershell
# 가상환경 활성화 확인
.\venv\Scripts\Activate.ps1

# backend 폴더로 이동
cd backend

# FastAPI 서버 실행
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 6.2 접속 확인

- API 문서: http://localhost:8000/docs
- 헬스 체크: http://localhost:8000/health
- 전체 헬스 체크: http://localhost:8000/health/all

---

## 7. 폴더 구조

```
weeslee-rag/
├── .env                    # 환경 변수 (git 제외)
├── .env.example            # 환경 변수 예시
├── .gitignore
├── CLAUDE.md               # Claude Code 가이드
├── SETUP_LOCAL.md          # 이 문서
├── backend/
│   ├── requirements.txt    # Python 의존성
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py         # FastAPI 앱
│   │   ├── api/            # API 라우터
│   │   │   ├── health.py
│   │   │   ├── collections.py
│   │   │   └── documents.py
│   │   ├── core/           # 핵심 설정
│   │   │   ├── config.py
│   │   │   └── database.py
│   │   ├── models/         # SQLAlchemy 모델
│   │   │   ├── collection.py
│   │   │   ├── document.py
│   │   │   ├── prompt.py
│   │   │   └── execution.py
│   │   ├── schemas/        # Pydantic 스키마
│   │   ├── services/       # 비즈니스 로직
│   │   │   ├── vectordb.py
│   │   │   └── ollama.py
│   │   ├── extractors/     # 문서 추출기
│   │   └── tasks/          # Celery 태스크
│   ├── tests/              # 테스트
│   └── alembic/            # DB 마이그레이션
├── chroma_data/            # VectorDB 데이터 (git 제외)
├── uploads/                # 업로드 파일 (git 제외)
└── docs/                   # 문서
    ├── 260422_Requirements_Clarification.md
    ├── 260422_DEV_Plan.md
    └── 260422_Development_Sequence.md
```

---

## 8. 문제 해결

### 8.1 PowerShell 스크립트 실행 오류

```powershell
# 실행 정책 변경
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 8.2 MySQL 연결 오류

```powershell
# MySQL 서비스 확인
net start mysql

# XAMPP 사용 시
C:\xampp\mysql\bin\mysql -u root -p
```

### 8.3 Ollama 연결 오류

```powershell
# Ollama 프로세스 확인
tasklist | findstr ollama

# Ollama 재시작
taskkill /IM ollama.exe /F
ollama serve
```

---

## 9. 다음 단계

1. 가상환경 생성 및 활성화
2. 의존성 패키지 설치
3. MySQL 데이터베이스 생성
4. Ollama 모델 다운로드
5. FastAPI 서버 실행 및 테스트
6. Git 커밋 및 푸시

---

**문서 끝**
