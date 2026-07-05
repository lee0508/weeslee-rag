---
name: weeslee-server-deploy
description: weeslee-rag 프로젝트를 회사 서버 192.168.0.207(내부), 218.148.21.12(외부)의 /data/weeslee/weeslee-rag 경로에 배포하고 웹 URL에서 테스트할 때 사용한다.
---

# weeslee Server Deploy Skill

## Purpose

이 Skill은 로컬에서 수정한 weeslee-rag 코드를 회사 서버에 배포하고 테스트할 때 사용한다.

## Server Information

Server:
- 192.168.0.207(내부), 218.148.21.12(내부)

Project path:
- /data/weeslee/weeslee-rag

Public URLs:
- Admin: https://server.weeslee.co.kr/weeslee-rag/frontend/admin.html
- User: https://server.weeslee.co.kr/weeslee-rag/frontend/rag-assistant.html

## Server Connection
1. SSH ssh weeslee@218.148.21.12 -p 2222. Navigate to project path: cd /data/weeslee/weeslee-rag
2. password: weeslee12#$

## Deployment Policy

1. 로컬 수정 파일을 먼저 정리한다.
2. 서버의 동일 파일 경로를 확인한다.
3. 배포 전 기존 파일 백업 여부를 판단한다.
4. 프론트 파일 수정 시 브라우저 캐시 문제를 고려한다.
5. 백엔드 파일 수정 시 서비스 재시작 필요 여부를 확인한다.
6. 배포 후 admin.html과 rag-assistant.html을 모두 테스트한다.

## Common Checks

- admin.html이 정상 로딩되는가?
- rag-assistant.html이 정상 로딩되는가?
- API 호출 경로가 서버 기준으로 맞는가?
- CORS 또는 404 오류가 없는가?
- Dataset Builder 버튼이 정상 동작하는가?
- 검색 결과가 사용자 페이지에 반영되는가?

## Output Format

1. 배포 대상 파일
2. 서버 반영 위치
3. 필요한 명령어
4. 재시작 필요 여부
5. 테스트 URL
6. 확인 결과