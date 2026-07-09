#!/bin/bash
set -euo pipefail

SERVICE_NAME="${1:-weeslee-rag-api.service}"
SERVICE_PORT="${2:-8080}"

SYSTEMD_PID="$(systemctl show -p MainPID --value "$SERVICE_NAME" 2>/dev/null || true)"
PORT_PID="$(ss -lntp 2>/dev/null | awk -v port=":${SERVICE_PORT}" '$4 ~ port { if (match($0, /pid=[0-9]+/)) { print substr($0, RSTART + 4, RLENGTH - 4); exit } }')"

echo "service_name=$SERVICE_NAME"
echo "service_port=$SERVICE_PORT"
echo "systemd_main_pid=${SYSTEMD_PID:-none}"
echo "port_owner_pid=${PORT_PID:-none}"

if [[ -z "${PORT_PID}" ]]; then
  echo "ERROR: ${SERVICE_PORT} 포트를 점유한 프로세스가 없습니다."
  exit 1
fi

if [[ -z "${SYSTEMD_PID}" || "${SYSTEMD_PID}" == "0" ]]; then
  echo "ERROR: systemd MainPID 를 확인할 수 없습니다."
  exit 1
fi

if [[ "${SYSTEMD_PID}" != "${PORT_PID}" ]]; then
  echo "ERROR: ${SERVICE_PORT} 포트를 systemd 관리 프로세스가 아닌 PID ${PORT_PID} 가 점유 중입니다."
  exit 1
fi

echo "OK: ${SERVICE_PORT} 포트를 systemd MainPID ${SYSTEMD_PID} 가 단독 점유 중입니다."
