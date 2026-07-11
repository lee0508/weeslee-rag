---
name: weeslee-rag-deploy-precheck
description: weeslee-rag 프로젝트에서 코드 수정, 배포, 테스트 전에 로컬 Git, 원격 GitHub, 회사 서버 /data/weeslee/weeslee-rag 경로의 실제 변경 상태를 함께 점검할 때 사용한다.
---

# weeslee-rag 코드 작업 / 배포 전 상태 확인 스킬

## 목적

`weeslee-rag` 프로젝트에서 코드 수정, 배포, 테스트를 진행하기 전에 반드시 로컬 Git 상태, 원격 Git 상태, 회사 서버의 실제 파일 변경 상태를 확인한다.

이 스킬의 목적은 다음과 같다.

```text
1. 로컬에서 수정한 코드와 Git 상태 확인
2. 원격 GitHub 저장소와 로컬 브랜치 상태 확인
3. 회사 서버 /data/weeslee/weeslee-rag 폴더의 실제 변경 파일 확인
4. scp 배포 또는 git pull 배포 전에 서버 변경분 덮어쓰기 방지
5. 코드 작업은 로컬에서 하고, 배포와 테스트는 회사 서버에서 진행한다는 원칙 유지
```

---

## 기본 작업 원칙

`weeslee-rag` 프로젝트는 다음 원칙을 따른다.

```text
코드 수정 작업: 로컬 Windows 개발 환경에서 진행
코드 배포 작업: 회사 서버에 반영
테스트 작업: 회사 서버에서 웹/API 기준으로 확인
회사 서버 프로젝트 경로: /data/weeslee/weeslee-rag
```

주의할 점은 다음과 같다.

```text
1. 로컬 코드가 최신이라고 단정하지 않는다.
2. 서버 코드가 Git 상태와 같다고 단정하지 않는다.
3. 이전에 scp 명령으로 서버에 직접 배포한 파일이 있을 수 있다.
4. 서버에서 직접 수정된 파일이 있을 수 있다.
5. 코드 수정 전에는 반드시 로컬 / 원격 / 서버 상태를 모두 확인한다.
```

---

## 1단계. 로컬 Git 상태 확인

코드 작업을 시작하기 전에 로컬 프로젝트 폴더에서 Git 상태를 확인한다.

예시 로컬 경로는 작업 환경에 따라 다를 수 있다.

```bash
cd weeslee-rag
git status
git branch
git log --oneline -5
```

확인해야 할 내용은 다음과 같다.

```text
1. 현재 브랜치가 main 또는 작업 대상 브랜치인지 확인
2. 수정된 파일이 있는지 확인
3. untracked 파일이 있는지 확인
4. 마지막 커밋이 무엇인지 확인
5. 아직 커밋하지 않은 변경 사항이 있는지 확인
```

특히 `git status` 결과에서 아래 상태가 있으면 바로 코드 수정하지 말고 먼저 판단해야 한다.

```text
modified:
deleted:
untracked files:
both modified:
```

---

## 2단계. 원격 GitHub 상태 확인

로컬 저장소와 원격 저장소의 차이를 확인한다.

```bash
git fetch origin
git status
git log --oneline --decorate --graph --all -10
```

현재 브랜치와 원격 브랜치 차이를 확인한다.

```bash
git log --oneline HEAD..origin/main
git log --oneline origin/main..HEAD
```

의미는 다음과 같다.

```text
git log --oneline HEAD..origin/main
→ 원격에는 있는데 로컬에는 없는 커밋 확인

git log --oneline origin/main..HEAD
→ 로컬에는 있는데 원격에는 없는 커밋 확인
```

판단 기준은 다음과 같다.

```text
1. 원격에 더 최신 커밋이 있으면 먼저 pull 또는 merge 필요
2. 로컬에만 있는 커밋이 있으면 push 여부 확인
3. 로컬 수정 파일이 있는 상태에서 pull 하면 충돌 가능성 있음
4. 충돌 가능성이 있으면 작업 전에 사용자에게 보고
```

---

## 3단계. 회사 서버 접속

코드 배포와 테스트는 회사 서버에서 진행한다.

회사 내부망 접속 예시:

```bash
ssh weeslee@192.168.0.207
```

회사 외부망 접속 예시:

```bash
ssh weeslee@218.148.21.12 -p 2222
```

서버 접속 후 프로젝트 폴더로 이동한다.

```bash
cd /data/weeslee/weeslee-rag
pwd
```

반드시 현재 위치가 아래 경로인지 확인한다.

```text
/data/weeslee/weeslee-rag
```

---

## 4단계. 서버 Git 상태 확인

서버 프로젝트 폴더에서 Git 상태를 확인한다.

```bash
cd /data/weeslee/weeslee-rag

git status
git branch
git log --oneline -5
```

원격 저장소와 서버 저장소의 차이도 확인한다.

```bash
git fetch origin
git status
git log --oneline HEAD..origin/main
git log --oneline origin/main..HEAD
```

확인해야 할 내용은 다음과 같다.

```text
1. 서버 브랜치가 main인지 확인
2. 서버에 수정된 파일이 있는지 확인
3. 서버에 untracked 파일이 있는지 확인
4. 서버가 원격보다 뒤처져 있는지 확인
5. 서버에만 존재하는 커밋이 있는지 확인
```

주의 사항:

```text
서버에서 git status 결과가 clean이 아니면 바로 git pull, scp 덮어쓰기, 코드 배포를 진행하지 않는다.
먼저 변경 파일 목록을 확인하고 사용자에게 보고한다.
```

---

## 5단계. 서버에서 어제 날짜 기준 파일 변경 확인

서버에는 과거에 scp 명령으로 직접 배포한 파일이 있을 수 있다.

따라서 Git 상태만 확인하지 말고, 서버 프로젝트 폴더에서 실제 파일 수정 시간을 기준으로 변경 파일을 확인해야 한다.

기준 경로:

```text
/data/weeslee/weeslee-rag
```

어제 00:00 이후 변경된 파일 확인:

```bash
cd /data/weeslee/weeslee-rag

YESTERDAY=$(date -d "yesterday" +%F)

find . \
  -type f \
  -newermt "$YESTERDAY 00:00:00" \
  ! -path "./.git/*" \
  ! -path "./venv/*" \
  ! -path "./.venv/*" \
  ! -path "./__pycache__/*" \
  ! -path "./node_modules/*" \
  -printf "%TY-%Tm-%Td %TH:%TM:%TS %p\n" \
  | sort
```

간단한 버전:

```bash
find /data/weeslee/weeslee-rag \
  -type f \
  -newermt "$(date -d 'yesterday' +%F) 00:00:00" \
  ! -path "*/.git/*" \
  | sort
```

변경 파일 개수만 확인:

```bash
find . \
  -type f \
  -newermt "$(date -d 'yesterday' +%F) 00:00:00" \
  ! -path "./.git/*" \
  | wc -l
```

최근 변경 파일 상위 50개 확인:

```bash
find . \
  -type f \
  ! -path "./.git/*" \
  -printf "%T@ %TY-%Tm-%Td %TH:%TM %p\n" \
  | sort -nr \
  | head -50
```

---

## 6단계. 서버 변경 파일 중 중요 파일 확인

어제 이후 변경된 파일 중 아래 파일들이 있으면 특히 주의한다.

```text
frontend/admin.html
frontend/rag-assistant.html
backend/*.py
backend/**/*.py
backend/databuilder/*.py
backend/api/*.py
backend/models/*.py
backend/services/*.py
docs/*.md
.env
docker-compose.yml
requirements.txt
```

중요 파일이 변경되어 있으면 다음을 확인한다.

```bash
git diff -- frontend/admin.html
git diff -- frontend/rag-assistant.html
git diff -- backend
git diff -- docs
```

Git 추적 파일이 아닌 경우에는 `ls -al`과 `stat`로 확인한다.

```bash
ls -al 변경파일경로
stat 변경파일경로
```

---

## 7단계. scp 배포 이력 가능성 확인

이 프로젝트는 로컬에서 `scp` 명령으로 서버에 직접 코드를 배포한 경우가 있을 수 있다.

따라서 서버 파일이 Git에 반영되지 않았을 수 있다.

확인 기준:

```text
1. git status에는 clean으로 보이지만 파일 수정 시간이 최근일 수 있음
2. git status에는 untracked 파일이 보일 수 있음
3. 서버에만 존재하는 임시 테스트 파일이 있을 수 있음
4. scp로 덮어쓴 파일은 Git 커밋 이력과 맞지 않을 수 있음
```

서버에서 최근 변경 파일을 확인한 뒤, Git 상태와 비교해야 한다.

```bash
git status --short
find . -type f -newermt "$(date -d 'yesterday' +%F) 00:00:00" ! -path "./.git/*" | sort
```

---

## 8단계. 배포 전 판단 기준

아래 조건을 모두 만족할 때만 배포를 진행한다.

```text
1. 로컬 Git 상태 확인 완료
2. 원격 GitHub 상태 확인 완료
3. 서버 Git 상태 확인 완료
4. 서버 어제 이후 변경 파일 확인 완료
5. 서버 변경 파일이 현재 작업과 충돌하지 않음
6. scp로 배포된 것으로 보이는 파일이 있는지 확인 완료
7. 변경 파일 백업 또는 커밋 필요 여부 판단 완료
```

아래 상황이면 배포하지 말고 먼저 사용자에게 보고한다.

```text
1. 서버에 git status modified 파일이 있음
2. 서버에 untracked 중요 파일이 있음
3. 서버 파일 수정 시간이 최근인데 Git에는 반영되지 않았음
4. 로컬과 서버의 같은 파일이 서로 다르게 수정되어 있음
5. 원격 GitHub와 서버 커밋이 다름
6. scp 배포 흔적이 있어 덮어쓰기 위험이 있음
```

---

## 9단계. 서버 변경분 백업 방법

배포 전 서버 변경 파일이 중요해 보이면 백업을 만든다.

백업 폴더 예시:

```bash
cd /data/weeslee/weeslee-rag

BACKUP_DIR="/data/weeslee/backup/weeslee-rag_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
```

변경 파일 목록 저장:

```bash
git status --short > "$BACKUP_DIR/git_status_short.txt"

find . \
  -type f \
  -newermt "$(date -d 'yesterday' +%F) 00:00:00" \
  ! -path "./.git/*" \
  | sort > "$BACKUP_DIR/recent_changed_files.txt"
```

전체 프로젝트를 압축 백업하는 경우:

```bash
tar \
  --exclude=".git" \
  --exclude="venv" \
  --exclude=".venv" \
  --exclude="node_modules" \
  -czf "$BACKUP_DIR/weeslee-rag_backup.tar.gz" \
  /data/weeslee/weeslee-rag
```

---

## 10단계. 로컬에서 서버로 scp 배포할 때 주의사항

scp로 파일을 배포할 때는 절대 전체 폴더를 무조건 덮어쓰지 않는다.

잘못된 예:

```bash
scp -r ./weeslee-rag weeslee@서버:/data/weeslee/
```

권장 방식:

```bash
scp frontend/admin.html weeslee@192.168.0.207:/data/weeslee/weeslee-rag/frontend/admin.html
```

또는 외부망:

```bash
scp -P 2222 frontend/admin.html weeslee@218.148.21.12:/data/weeslee/weeslee-rag/frontend/admin.html
```

여러 파일을 배포할 때도 변경 파일만 명확히 지정한다.

```bash
scp backend/databuilder/run_embed_step6.py \
  weeslee@192.168.0.207:/data/weeslee/weeslee-rag/backend/databuilder/run_embed_step6.py
```

scp 배포 후 서버에서 반드시 확인한다.

```bash
cd /data/weeslee/weeslee-rag

git status --short
ls -al frontend/admin.html
stat frontend/admin.html
```

---

## 11단계. git pull 방식으로 서버 배포할 때 주의사항

서버에서 `git pull`을 하기 전에는 반드시 서버 상태가 clean인지 확인한다.

```bash
cd /data/weeslee/weeslee-rag

git status
```

clean 상태이면 pull 가능하다.

```bash
git pull origin main
```

clean 상태가 아니면 pull하지 않는다.

먼저 아래 내용을 확인한다.

```bash
git status --short
git diff
```

필요하면 서버 변경분을 백업하거나 별도 브랜치로 보관한다.

```bash
git checkout -b backup/server-change-$(date +%Y%m%d_%H%M%S)
git add .
git commit -m "backup: server changes before deployment"
```

단, 커밋 여부는 사용자에게 먼저 보고하고 판단을 받은 뒤 진행한다.

---

## 12단계. 배포 후 기본 테스트

코드 배포 후에는 서버에서 기본 상태를 확인한다.

백엔드 상태 확인 예시:

```bash
curl http://localhost:8000/api/health
```

또는 서비스 URL 기준으로 확인한다.

```text
관리자 페이지:
https://server.weeslee.co.kr/weeslee-rag/frontend/admin.html

사용자 검색 페이지:
https://server.weeslee.co.kr/weeslee-rag/frontend/rag-assistant.html
```

프론트 파일을 수정한 경우에는 브라우저 캐시 영향이 있을 수 있으므로 강력 새로고침을 안내한다.

```text
Chrome 기준:
Ctrl + F5
또는
개발자도구 열기 → 새로고침 버튼 우클릭 → Empty Cache and Hard Reload
```

---

## 13단계. 작업 전 보고 형식

Codex 또는 Claude는 코드 수정 전에 아래 형식으로 상태를 보고한다.

```text
[weeslee-rag 작업 전 상태 확인]

1. 로컬 Git 상태
- 현재 브랜치:
- 수정 파일:
- untracked 파일:
- 마지막 커밋:

2. 원격 GitHub 상태
- origin/main과 차이:
- 로컬에만 있는 커밋:
- 원격에만 있는 커밋:

3. 서버 Git 상태
- 서버 경로: /data/weeslee/weeslee-rag
- 현재 브랜치:
- 수정 파일:
- untracked 파일:
- 마지막 커밋:

4. 서버 최근 변경 파일
- 기준: 어제 00:00 이후
- 변경 파일 개수:
- 주요 변경 파일:

5. 배포 위험 판단
- 서버 변경분 덮어쓰기 위험:
- scp 배포 흔적:
- git pull 가능 여부:
- 백업 필요 여부:

6. 다음 작업 제안
- 바로 작업 가능:
- 먼저 백업 필요:
- 사용자 확인 필요:
```

---

## 14단계. 절대 금지 사항

다음 작업은 사용자 확인 없이 진행하지 않는다.

```text
1. 서버에서 git reset --hard 실행
2. 서버에서 git clean -fd 실행
3. 서버 파일 전체 덮어쓰기
4. scp -r로 프로젝트 전체 덮어쓰기
5. 서버 변경 파일 삭제
6. 서버의 untracked 파일 삭제
7. 서버에서 변경된 admin.html, rag-assistant.html 덮어쓰기
8. DB 마이그레이션 즉시 실행
9. 운영 서비스 재시작
10. .env 파일 수정 또는 덮어쓰기
```

---

## 15단계. 최종 원칙

`weeslee-rag` 프로젝트에서는 코드 수정 자체보다 먼저 현재 상태 확인이 우선이다.

항상 아래 순서를 지킨다.

```text
1. 로컬 상태 확인
2. 원격 GitHub 상태 확인
3. 서버 Git 상태 확인
4. 서버 최근 변경 파일 확인
5. 서버 변경분 덮어쓰기 위험 판단
6. 필요한 경우 백업
7. 코드 수정
8. 배포
9. 서버 테스트
10. 결과 보고
```

이 절차를 생략하면 로컬 코드, GitHub 코드, 서버 코드가 서로 달라져서 이후 Dataset Builder, OCR/Parser, FAISS, Graph, LLM Wiki 기능 테스트에 혼선이 발생할 수 있다.
