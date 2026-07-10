#!/bin/bash
# weeslee-rag 데이터셋 빌드 상태 확인 도구 (단일 출력 wrapper)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ -x "$PROJECT_ROOT/.venv/bin/python3" ]]; then
    PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "Python 실행 파일을 찾을 수 없습니다. python3 또는 python이 필요합니다." >&2
    exit 1
fi

FORWARD_ARGS=()

if [[ $# -gt 0 && "${1:-}" != -* ]]; then
    FORWARD_ARGS+=(--source-id "$1")
    shift
fi

FORWARD_ARGS+=("$@")

exec "$PYTHON_BIN" "$PROJECT_ROOT/backend/scripts/monitor_dataset_build.py" "${FORWARD_ARGS[@]}"
