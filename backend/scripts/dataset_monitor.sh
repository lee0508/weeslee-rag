#!/bin/bash
# weeslee-rag 데이터셋 빌드 모니터링 도구 (watch wrapper)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "Python 실행 파일을 찾을 수 없습니다. python3 또는 python이 필요합니다." >&2
    exit 1
fi

usage() {
    cat <<'EOF'
Usage: ./backend/scripts/dataset_monitor.sh [OPTIONS] [source_id]

Options:
  -s, --source-id ID    Monitor specific source_id
  -i, --interval SEC    Refresh interval in seconds (default: 3)
  --all-sources         Show latest source summary in watch mode
  --limit N             Limit sources for --all-sources (default: 10)
  --json                Output JSON
  -h, --help            Show this help

Examples:
  ./backend/scripts/dataset_monitor.sh src_20260710_122653_eafb7a
  ./backend/scripts/dataset_monitor.sh -s src_20260710_122653_eafb7a -i 5
  ./backend/scripts/dataset_monitor.sh --all-sources --limit 5
EOF
}

FORWARD_ARGS=(--watch)

while [[ $# -gt 0 ]]; do
    case "$1" in
        -s|--source-id)
            [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 1; }
            FORWARD_ARGS+=(--source-id "$2")
            shift 2
            ;;
        -i|--interval)
            [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 1; }
            FORWARD_ARGS+=(--interval "$2")
            shift 2
            ;;
        --all-sources|--json)
            FORWARD_ARGS+=("$1")
            shift
            ;;
        --limit)
            [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 1; }
            FORWARD_ARGS+=(--limit "$2")
            shift 2
            ;;
        --watch)
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            echo "Unknown option: $1" >&2
            usage
            exit 1
            ;;
        *)
            FORWARD_ARGS+=(--source-id "$1")
            shift
            ;;
    esac
done

exec "$PYTHON_BIN" "$PROJECT_ROOT/backend/scripts/monitor_dataset_build.py" "${FORWARD_ARGS[@]}"
