#!/bin/bash
# 192.168.0.207 서버에서 NAS 마운트를 설정하는 스크립트

set -e

echo "=========================================="
echo "weeslee-rag NAS 마운트 설정 스크립트"
echo "=========================================="
echo ""

# 설정값
NAS_IP="192.168.0.56"
NAS_SHARE="W2_프로젝트폴더"
MOUNT_POINT="/mnt/w2_project"
CREDS_FILE="/etc/cifs-credentials"

# NAS 계정 정보 (사전 설정)
NAS_USER="ymhpro"
NAS_PASS="ymhpro123"

# 1. 필요 패키지 설치
echo "[1/6] cifs-utils 패키지 설치 중..."
sudo apt-get update -qq
sudo apt-get install -y cifs-utils

# 2. 마운트 포인트 생성
echo "[2/6] 마운트 포인트 생성 중..."
sudo mkdir -p "$MOUNT_POINT"

# 3. 인증 정보 파일 생성
echo "[3/6] 인증 정보 파일 설정..."
sudo tee "$CREDS_FILE" > /dev/null << EOF
username=$NAS_USER
password=$NAS_PASS
domain=WORKGROUP
EOF

sudo chmod 600 "$CREDS_FILE"
sudo chown root:root "$CREDS_FILE"
echo "  → 인증 정보 파일 생성 완료: $CREDS_FILE"

# 4. 수동 마운트 테스트
echo "[4/6] 수동 마운트 테스트 중..."
if mountpoint -q "$MOUNT_POINT"; then
    echo "  → 이미 마운트되어 있음"
else
    sudo mount -t cifs \
        "//$NAS_IP/$NAS_SHARE" \
        "$MOUNT_POINT" \
        -o credentials="$CREDS_FILE",iocharset=utf8,file_mode=0755,dir_mode=0755,vers=1.0,uid=1000,gid=1000

    if mountpoint -q "$MOUNT_POINT"; then
        echo "  → 마운트 성공!"
    else
        echo "  → 마운트 실패"
        exit 1
    fi
fi

# 5. 마운트 상태 확인
echo "[5/6] 마운트 상태 확인..."
df -h "$MOUNT_POINT"
echo ""
echo "폴더 목록 (상위 10개):"
ls "$MOUNT_POINT" | head -10

# 6. fstab 자동 마운트 설정
echo "[6/6] fstab 자동 마운트 설정..."
FSTAB_ENTRY="//$NAS_IP/$NAS_SHARE $MOUNT_POINT cifs credentials=$CREDS_FILE,iocharset=utf8,file_mode=0755,dir_mode=0755,vers=1.0,uid=1000,gid=1000,nofail,_netdev 0 0"

if grep -q "$MOUNT_POINT" /etc/fstab; then
    echo "  → fstab에 이미 항목이 존재함"
else
    echo "$FSTAB_ENTRY" | sudo tee -a /etc/fstab > /dev/null
    echo "  → fstab에 추가 완료"
fi

echo ""
echo "=========================================="
echo "NAS 마운트 설정 완료!"
echo "=========================================="
echo ""
echo "마운트 경로: $MOUNT_POINT"
echo "NAS 공유: //$NAS_IP/$NAS_SHARE"
echo ""
echo "한글 폴더 테스트:"
ls -la "$MOUNT_POINT" | grep -E "국내|해외|참고" || echo "(한글 폴더 접근 확인 필요)"
