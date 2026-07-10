#!/bin/bash
# weeslee-rag 데이터셋 빌드 상태 확인 도구 (단일 출력)

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'

DATA_ROOT="/data/weeslee/weeslee-rag/data"
API_URL="http://127.0.0.1:8080"

# source_id 인자
SOURCE_ID="$1"

# 최신 source_id 찾기
get_latest_source_id() {
    find "$DATA_ROOT/documents" -name "snapshot_*_src_*.json" -type f -printf '%T@ %p\n' 2>/dev/null | \
        sort -rn | head -1 | grep -oP 'src_[0-9]{8}_[0-9]{6}_[a-f0-9]+' | head -1
}

if [ -z "$SOURCE_ID" ]; then
    SOURCE_ID=$(get_latest_source_id)
fi

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║          weeslee-rag Dataset Build Status                            ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# 시스템 상태
echo -e "${BOLD}[SYSTEM]${NC}"
cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1 2>/dev/null || echo "N/A")
mem_info=$(free -h 2>/dev/null | awk '/^Mem:/ {printf "%s / %s", $3, $2}' || echo "N/A")
disk_info=$(df -h "$DATA_ROOT" 2>/dev/null | awk 'NR==2 {printf "%s / %s (%s)", $3, $2, $5}' || echo "N/A")

uvicorn_pid=$(pgrep -f "uvicorn.*8080" | head -1)
if [ -n "$uvicorn_pid" ]; then
    uvicorn_cpu=$(ps -p $uvicorn_pid -o %cpu= 2>/dev/null | tr -d ' ')
    uvicorn_mem=$(ps -p $uvicorn_pid -o %mem= 2>/dev/null | tr -d ' ')
    uptime_sec=$(ps -p $uvicorn_pid -o etimes= 2>/dev/null | tr -d ' ')
    uptime_min=$((uptime_sec / 60))
    echo -e "  API Server: ${GREEN}● RUNNING${NC} (PID: $uvicorn_pid, Uptime: ${uptime_min}min)"
    echo -e "  Server CPU: ${YELLOW}${uvicorn_cpu}%${NC}  MEM: ${YELLOW}${uvicorn_mem}%${NC}"
else
    echo -e "  API Server: ${RED}● STOPPED${NC}"
fi
echo -e "  System CPU: ${cpu_usage}%  MEM: $mem_info  DISK: $disk_info"
echo ""

# 데이터셋 상태
echo -e "${BOLD}[DATASET]${NC}"
if [ -z "$SOURCE_ID" ]; then
    echo -e "  ${YELLOW}No active dataset found${NC}"
else
    echo -e "  Source ID: ${GREEN}$SOURCE_ID${NC}"

    # 각 단계별 파일 수
    snapshot_count=$(find "$DATA_ROOT/documents" -name "snapshot_*_${SOURCE_ID}_*.json" -type f 2>/dev/null | wc -l)

    # FAISS 파일 확인
    faiss_index=$(ls "$DATA_ROOT/indexes/faiss/"*"${SOURCE_ID}"*.index 2>/dev/null | head -1)
    faiss_meta=$(ls "$DATA_ROOT/indexes/faiss/"*"${SOURCE_ID}"*_metadata.jsonl 2>/dev/null | head -1)

    # Graph 파일 확인
    graph_file=$(ls "$DATA_ROOT/graph/"*"${SOURCE_ID}"*.json 2>/dev/null | head -1)

    # Wiki 폴더 확인
    wiki_dir=$(ls -d "$DATA_ROOT/wiki/"*"${SOURCE_ID}"* 2>/dev/null | head -1)

    echo ""
    echo -e "${BOLD}[PIPELINE STEPS]${NC}"

    # Step 1-4: OCR/Parse
    if [ "$snapshot_count" -gt 0 ]; then
        echo -e "  Step 1-4 OCR/Parse:     ${GREEN}● DONE${NC} ($snapshot_count snapshots)"
    else
        echo -e "  Step 1-4 OCR/Parse:     ${RED}○ PENDING${NC}"
    fi

    # Step 5: Metadata (snapshot이 있으면 완료)
    if [ "$snapshot_count" -gt 0 ]; then
        echo -e "  Step 5   Metadata:      ${GREEN}● DONE${NC}"
    else
        echo -e "  Step 5   Metadata:      ${RED}○ PENDING${NC}"
    fi

    # Step 6: FAISS
    if [ -n "$faiss_index" ] && [ -n "$faiss_meta" ]; then
        faiss_size=$(du -h "$faiss_index" 2>/dev/null | cut -f1)
        meta_lines=$(wc -l < "$faiss_meta" 2>/dev/null || echo "0")
        echo -e "  Step 6   FAISS:         ${GREEN}● DONE${NC} (${faiss_size}, ${meta_lines} chunks)"
    else
        echo -e "  Step 6   FAISS:         ${YELLOW}○ IN PROGRESS / PENDING${NC}"
    fi

    # Step 7: Graph
    if [ -n "$graph_file" ]; then
        node_count=$(grep -oP '"nodes":\s*\[' "$graph_file" 2>/dev/null && grep -c '"id"' "$graph_file" 2>/dev/null || echo "?")
        echo -e "  Step 7   Graph:         ${GREEN}● DONE${NC}"
    else
        echo -e "  Step 7   Graph:         ${RED}○ PENDING${NC}"
    fi

    # Step 8: Wiki
    if [ -n "$wiki_dir" ]; then
        wiki_count=$(find "$wiki_dir" -name "*.md" -type f 2>/dev/null | wc -l)
        echo -e "  Step 8   Wiki:          ${GREEN}● DONE${NC} ($wiki_count pages)"
    else
        echo -e "  Step 8   Wiki:          ${RED}○ PENDING${NC}"
    fi
fi

echo ""

# FAISS 인덱스 상세
echo -e "${BOLD}[FAISS INDEXES]${NC}"
faiss_files=$(ls -la "$DATA_ROOT/indexes/faiss/"*.index 2>/dev/null | tail -5)
if [ -n "$faiss_files" ]; then
    echo "$faiss_files" | while read line; do
        fname=$(echo "$line" | awk '{print $NF}' | xargs basename 2>/dev/null)
        fsize=$(echo "$line" | awk '{print $5}')
        ftime=$(echo "$line" | awk '{print $6, $7, $8}')
        echo -e "  ${GREEN}✓${NC} $fname (${fsize} bytes, $ftime)"
    done
else
    echo -e "  ${DIM}No FAISS indexes found${NC}"
fi

echo ""

# 최근 파일 활동
echo -e "${BOLD}[RECENT ACTIVITY]${NC} (last 5 min)"
recent=$(find "$DATA_ROOT" -type f -mmin -5 2>/dev/null | head -5)
if [ -n "$recent" ]; then
    echo "$recent" | while read fpath; do
        fname=$(basename "$fpath")
        ftime=$(stat -c '%y' "$fpath" 2>/dev/null | cut -d'.' -f1)
        echo -e "  ${CYAN}$ftime${NC} $fname"
    done
else
    echo -e "  ${DIM}No recent file changes${NC}"
fi

echo ""

# API 상태
echo -e "${BOLD}[API HEALTH]${NC}"
health=$(curl -s --max-time 3 "$API_URL/api/health" 2>/dev/null)
if [ -n "$health" ]; then
    status=$(echo "$health" | grep -oP '"status"\s*:\s*"\K[^"]+' 2>/dev/null || echo "unknown")
    if [ "$status" = "healthy" ]; then
        echo -e "  ${GREEN}● API Healthy${NC}"
    else
        echo -e "  ${YELLOW}● Status: $status${NC}"
    fi
else
    echo -e "  ${RED}● API Not Responding${NC} (server busy or timeout)"
fi

echo ""
echo -e "${DIM}Usage: ./dataset_status.sh [source_id]${NC}"
echo -e "${DIM}Example: ./dataset_status.sh src_20260710_122653_eafb7a${NC}"
echo ""
