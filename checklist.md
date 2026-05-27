# LLM Wiki 8단계 API 점검 체크리스트

- [x] `/api/wiki/build` 호출 경로와 `build_project_wiki.py` 확인
- [x] 서버 로그에서 500 발생 시각과 서비스 재시작 시각 대조
- [x] Wiki build에 `source_id`와 `snapshot` 전달 연결
- [x] RAG 근거 수집 타임아웃 조정
- [x] 정적 검증 실행
- [x] 서버 기준 단일 Wiki 생성 검증
- [x] 변경 사항 커밋
- [x] 서버 배포 및 서비스 재시작
