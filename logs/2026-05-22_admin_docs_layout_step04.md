# 2026-05-22 admin docs layout step 4

- 완료 시각: 2026-05-22
- 단계: 원격 배포, 서비스 재시작, 헬스체크

## 실행 내용

- 원격 Git 상태 확인
- `ssh -p 2222 weeslee@218.148.21.12 "cd /data/weeslee/weeslee-rag && git pull origin main"`
- 원격 `backend` 작업 디렉터리에서 `uvicorn app.main:app --host 0.0.0.0 --port 8080` 재시작
- 내부 헬스체크 `curl http://127.0.0.1:8080/api/health`
- 공인 경로 헬스체크 `GET https://server.weeslee.co.kr/weeslee-rag/api/health/all`

## 결과

- 원격 서버는 `d61209e -> ba2bbc8`로 fast-forward pull 됐다.
- `8080` 포트 프로세스 PID `3670675`가 기동 중이다.
- `/tmp/uvicorn.log`에 `Application startup complete`와 `Uvicorn running on http://0.0.0.0:8080`가 기록됐다.
- 내부 헬스 응답: `{\"status\":\"healthy\"}`
- 공인 경로 헬스 응답: `{\"status\":\"healthy\", ... }`

## 비고

- 원격 작업트리에는 기존과 동일하게 `data/*`, `platform_config/` 쪽 로컬 변경이 남아 있었지만 코드 pull은 충돌 없이 진행됐다.
- 재시작 첫 시도는 PowerShell 인용 문제와 SSH 타임아웃 때문에 직접 상태 확인으로 후속 검증했다.
