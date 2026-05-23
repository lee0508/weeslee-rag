# NAS 마운트 설정 가이드

**작성일**: 2026-05-19
**대상 서버**: 192.168.0.207 (Ubuntu)
**NAS IP**: 192.168.0.56 (diskstation)
**공유 폴더**: W2_프로젝트폴더
**SMB 버전**: 1.0 (NT1)

---

## 1. 개요

weeslee-rag 운영 서버(192.168.0.207)에서 회사 NAS(192.168.0.105)의 문서에 직접 접근할 수 있도록 CIFS/SMB 마운트를 설정합니다.

### 마운트 후 경로 매핑

| 원본 경로 | 마운트 후 서버 경로 |
|-----------|---------------------|
| `\\diskstation\W2_프로젝트폴더` | `/mnt/w2_project` |
| `W:\01. 국내사업폴더` | `/mnt/w2_project/01. 국내사업폴더` |
| `W:\02. 해외사업폴더` | `/mnt/w2_project/02. 해외사업폴더` |
| `W:\00. RAG 소스` | `/mnt/w2_project/00. RAG 소스` |

---

## 2. 사전 준비

### 2.1 필요 패키지 설치

```bash
sudo apt-get update
sudo apt-get install -y cifs-utils
```

### 2.2 마운트 포인트 생성

```bash
sudo mkdir -p /mnt/w2_project
```

### 2.3 인증 정보 파일 생성

NAS 접속 계정 정보를 별도 파일로 관리합니다 (보안상 fstab에 직접 기재하지 않음).

```bash
sudo nano /etc/cifs-credentials
```

아래 내용 입력 (실제 NAS 계정으로 변경):

```text
username=NAS_사용자_ID
password=NAS_비밀번호
domain=WORKGROUP
```

파일 권한 설정 (root만 읽기 가능):

```bash
sudo chmod 600 /etc/cifs-credentials
sudo chown root:root /etc/cifs-credentials
```

---

## 3. 마운트 설정

### 3.1 수동 마운트 테스트

먼저 수동으로 마운트하여 정상 동작 확인:

```bash
sudo mount -t cifs \
  "//192.168.0.56/W2_프로젝트폴더" \
  /mnt/w2_project \
  -o credentials=/etc/cifs-credentials,iocharset=utf8,file_mode=0755,dir_mode=0755,vers=1.0,uid=1000,gid=1000
```

### 3.2 마운트 확인

```bash
# 마운트 상태 확인
df -h | grep w2_project

# 파일 목록 확인 (한글 폴더명 정상 표시 확인)
ls -la "/mnt/w2_project/01. 국내사업폴더" | head -20
```

### 3.3 자동 마운트 설정 (fstab)

서버 재부팅 시 자동 마운트되도록 `/etc/fstab`에 추가:

```bash
sudo nano /etc/fstab
```

파일 하단에 아래 라인 추가:

```text
//192.168.0.56/W2_프로젝트폴더 /mnt/w2_project cifs credentials=/etc/cifs-credentials,iocharset=utf8,file_mode=0755,dir_mode=0755,vers=1.0,uid=1000,gid=1000,nofail,_netdev 0 0
```

### 3.4 fstab 적용 및 확인

```bash
# fstab 문법 검증
sudo mount -a

# 마운트 상태 확인
mount | grep w2_project
```

---

## 4. 마운트 옵션 설명

| 옵션 | 설명 |
|------|------|
| `credentials` | 인증 정보 파일 경로 |
| `iocharset=utf8` | 한글 파일명/폴더명 지원 |
| `file_mode=0755` | 파일 권한 (읽기/실행) |
| `dir_mode=0755` | 디렉토리 권한 |
| `vers=1.0` | SMB 프로토콜 버전 (diskstation은 SMB1만 지원) |
| `uid=1000` | 마운트된 파일의 소유자 UID (weeslee 사용자) |
| `gid=1000` | 마운트된 파일의 소유 그룹 GID |
| `nofail` | 마운트 실패 시 부팅 계속 진행 |
| `_netdev` | 네트워크 준비 후 마운트 시도 |

---

## 5. weeslee-rag 설정 연동

### 5.1 knowledge_source_service.py 경로 설정

마운트 완료 후, weeslee-rag 백엔드에서 NAS 경로를 인식하도록 설정합니다.

**파일 위치**: `backend/app/services/knowledge_source_service.py`

```python
# NAS 마운트 경로 설정
NAS_MOUNT_PATH = Path("/mnt/w2_project")

# Windows 경로를 Linux 마운트 경로로 변환
def convert_windows_path(windows_path: str) -> Path:
    """
    W:\01. 국내사업폴더\... → /mnt/w2_project/01. 국내사업폴더/...
    \\diskstation\W2_프로젝트폴더\... → /mnt/w2_project/...
    """
    path = windows_path

    # UNC 경로 변환
    if path.startswith("\\\\"):
        # \\diskstation\W2_프로젝트폴더\... 형식
        parts = path.split("\\")
        if len(parts) > 3:
            relative = "/".join(parts[4:])  # 공유폴더명 이후 경로
            return NAS_MOUNT_PATH / relative

    # 드라이브 문자 경로 변환
    if path.startswith("W:"):
        relative = path[3:].replace("\\", "/")
        return NAS_MOUNT_PATH / relative

    return Path(path)
```

### 5.2 환경변수 설정 (선택사항)

`.env` 파일에 마운트 경로 추가:

```bash
# NAS 마운트 경로
NAS_MOUNT_PATH=/mnt/w2_project
NAS_DOMESTIC_PATH=/mnt/w2_project/01. 국내사업폴더
```

---

## 6. 문제 해결

### 6.1 마운트 실패 시

```bash
# 에러 로그 확인
dmesg | tail -20

# NAS 연결 테스트
ping 192.168.0.105

# SMB 포트 연결 테스트
nc -zv 192.168.0.105 445
```

### 6.2 한글 깨짐 시

`iocharset=utf8` 옵션이 적용되었는지 확인:

```bash
mount | grep w2_project
```

출력에 `iocharset=utf8`이 포함되어야 합니다.

### 6.3 권한 오류 시

```bash
# 현재 사용자 UID/GID 확인
id

# 마운트 옵션의 uid, gid 값을 위 결과와 일치시킴
```

### 6.4 SMB 버전 호환 문제

NAS가 구버전 SMB만 지원하는 경우:

```bash
# vers=2.0 또는 vers=1.0으로 변경
sudo mount -t cifs "//192.168.0.105/W2_프로젝트폴더" /mnt/w2_project \
  -o credentials=/etc/cifs-credentials,iocharset=utf8,vers=2.0
```

---

## 7. 마운트 상태 모니터링

### 7.1 상태 확인 스크립트

```bash
#!/bin/bash
# /usr/local/bin/check_nas_mount.sh

MOUNT_POINT="/mnt/w2_project"

if mountpoint -q "$MOUNT_POINT"; then
    echo "[OK] NAS mounted at $MOUNT_POINT"
    ls "$MOUNT_POINT" | head -5
else
    echo "[ERROR] NAS not mounted!"
    # 자동 재마운트 시도
    sudo mount -a
fi
```

### 7.2 크론잡 등록 (선택사항)

```bash
# 5분마다 마운트 상태 확인
*/5 * * * * /usr/local/bin/check_nas_mount.sh >> /var/log/nas_mount.log 2>&1
```

---

## 8. 체크리스트

- [ ] cifs-utils 패키지 설치
- [ ] /mnt/w2_project 디렉토리 생성
- [ ] /etc/cifs-credentials 파일 생성 및 권한 설정
- [ ] 수동 마운트 테스트 성공
- [ ] 한글 폴더명 정상 표시 확인
- [ ] /etc/fstab 자동 마운트 설정
- [ ] 서버 재부팅 후 자동 마운트 확인
- [ ] weeslee-rag 백엔드 경로 변환 로직 적용

---

## 9. 참고 명령어

```bash
# 마운트 해제
sudo umount /mnt/w2_project

# 강제 마운트 해제 (연결 끊김 시)
sudo umount -l /mnt/w2_project

# NAS 공유 폴더 목록 확인
smbclient -L //192.168.0.105 -U NAS_사용자_ID

# 마운트된 파일 시스템 정보
df -Th /mnt/w2_project
```
