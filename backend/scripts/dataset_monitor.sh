#!/bin/bash
# weeslee-rag 데이터셋 빌드 모니터링 도구 (htop/top 스타일)

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color
BOLD='\033[1m'
DIM='\033[2m'

# 경로 설정
DATA_ROOT="/data/weeslee/weeslee-rag/data"
API_URL="http://127.0.0.1:8080"

# 화면 초기화 함수
clear_screen() {
    clear
    tput cup 0 0
}

# 헤더 출력
print_header() {
    local cols=$(tput cols)
    local title="weeslee-rag Dataset Build Monitor"
    local now=$(date '+%Y-%m-%d %H:%M:%S')

    echo -e "${BOLD}${WHITE}╔$(printf '═%.0s' $(seq 1 $((cols-2))))╗${NC}"
    printf "${BOLD}${WHITE}║${NC} ${CYAN}%-40s${NC} %*s ${BOLD}${WHITE}║${NC}\n" "$title" $((cols-46)) "$now"
    echo -e "${BOLD}${WHITE}╠$(printf '═%.0s' $(seq 1 $((cols-2))))╣${NC}"
}

# 시스템 상태 출력
print_system_status() {
    local cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
    local mem_info=$(free -h | awk '/^Mem:/ {printf "%s / %s (%.1f%%)", $3, $2, $3/$2*100}')
    local disk_info=$(df -h "$DATA_ROOT" 2>/dev/null | awk 'NR==2 {printf "%s / %s (%s)", $3, $2, $5}')

    # uvicorn 프로세스 상태
    local uvicorn_pid=$(pgrep -f "uvicorn.*8080" | head -1)
    local uvicorn_status="${RED}● STOPPED${NC}"
    local uvicorn_cpu="N/A"
    local uvicorn_mem="N/A"

    if [ -n "$uvicorn_pid" ]; then
        uvicorn_status="${GREEN}● RUNNING${NC} (PID: $uvicorn_pid)"
        uvicorn_cpu=$(ps -p $uvicorn_pid -o %cpu= 2>/dev/null | tr -d ' ')
        uvicorn_mem=$(ps -p $uvicorn_pid -o %mem= 2>/dev/null | tr -d ' ')
    fi

    echo -e "${BOLD}${WHITE}║${NC} ${BOLD}SYSTEM${NC}                                                              ${BOLD}${WHITE}║${NC}"
    printf "${BOLD}${WHITE}║${NC}   CPU: ${YELLOW}%-10s${NC}  MEM: ${YELLOW}%-25s${NC}  DISK: ${YELLOW}%-20s${NC} ${BOLD}${WHITE}║${NC}\n" "${cpu_usage}%" "$mem_info" "$disk_info"
    printf "${BOLD}${WHITE}║${NC}   API Server: %-60s ${BOLD}${WHITE}║${NC}\n" "$uvicorn_status"
    printf "${BOLD}${WHITE}║${NC}   Server CPU: ${CYAN}%-8s${NC}  Server MEM: ${CYAN}%-8s${NC}                              ${BOLD}${WHITE}║${NC}\n" "${uvicorn_cpu}%" "${uvicorn_mem}%"
    echo -e "${BOLD}${WHITE}╠$(printf '═%.0s' $(seq 1 $(($(tput cols)-2))))╣${NC}"
}

# 최신 source_id 찾기
get_latest_source_id() {
    # documents 폴더에서 가장 최근 스냅샷의 source_id 추출
    local latest=$(find "$DATA_ROOT/documents" -name "snapshot_*_src_*.json" -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | awk '{print $2}')
    if [ -n "$latest" ]; then
        echo "$latest" | grep -oP 'src_[0-9]{8}_[0-9]{6}_[a-f0-9]+' | head -1
    fi
}

# 데이터셋 빌드 상태 출력
print_dataset_status() {
    local source_id="${1:-$(get_latest_source_id)}"

    if [ -z "$source_id" ]; then
        echo -e "${BOLD}${WHITE}║${NC} ${YELLOW}No active dataset build found${NC}                                        ${BOLD}${WHITE}║${NC}"
        return
    fi

    echo -e "${BOLD}${WHITE}║${NC} ${BOLD}DATASET BUILD${NC}                                                         ${BOLD}${WHITE}║${NC}"
    printf "${BOLD}${WHITE}║${NC}   Source ID: ${GREEN}%-55s${NC} ${BOLD}${WHITE}║${NC}\n" "$source_id"

    # 각 단계별 파일 수 계산
    local snapshot_count=$(find "$DATA_ROOT/documents" -name "snapshot_*_${source_id}_*.json" -type f 2>/dev/null | wc -l)
    local faiss_exists=$(ls "$DATA_ROOT/indexes/faiss/"*"${source_id}"* 2>/dev/null | wc -l)
    local graph_exists=$(ls "$DATA_ROOT/graph/"*"${source_id}"* 2>/dev/null | wc -l)
    local wiki_exists=$(ls -d "$DATA_ROOT/wiki/"*"${source_id}"* 2>/dev/null | wc -l)

    echo -e "${BOLD}${WHITE}╠$(printf '═%.0s' $(seq 1 $(($(tput cols)-2))))╣${NC}"
    echo -e "${BOLD}${WHITE}║${NC} ${BOLD}PIPELINE STEPS${NC}                                                        ${BOLD}${WHITE}║${NC}"

    # Step 상태 표시
    print_step_status "Step 1-3" "Source/Scan" "$snapshot_count" "docs"
    print_step_status "Step 4" "OCR/Parse" "$snapshot_count" "snapshots"
    print_step_status "Step 5" "Metadata" "$snapshot_count" "docs"
    print_step_status "Step 6" "Chunk/Embed/FAISS" "$faiss_exists" "files"
    print_step_status "Step 7" "Graph Build" "$graph_exists" "files"
    print_step_status "Step 8" "Wiki Build" "$wiki_exists" "dirs"

    # FAISS 인덱스 상세 정보
    echo -e "${BOLD}${WHITE}╠$(printf '═%.0s' $(seq 1 $(($(tput cols)-2))))╣${NC}"
    echo -e "${BOLD}${WHITE}║${NC} ${BOLD}FAISS INDEX${NC}                                                           ${BOLD}${WHITE}║${NC}"

    local faiss_files=$(ls -la "$DATA_ROOT/indexes/faiss/"*"${source_id}"* 2>/dev/null)
    if [ -n "$faiss_files" ]; then
        echo "$faiss_files" | while read line; do
            local fname=$(echo "$line" | awk '{print $NF}' | xargs basename 2>/dev/null)
            local fsize=$(echo "$line" | awk '{print $5}')
            if [ -n "$fname" ]; then
                printf "${BOLD}${WHITE}║${NC}   ${GREEN}✓${NC} %-50s %10s bytes ${BOLD}${WHITE}║${NC}\n" "$fname" "$fsize"
            fi
        done
    else
        printf "${BOLD}${WHITE}║${NC}   ${RED}✗${NC} No FAISS index for this source_id                               ${BOLD}${WHITE}║${NC}\n"
    fi
}

# 단계 상태 출력 헬퍼
print_step_status() {
    local step="$1"
    local name="$2"
    local count="$3"
    local unit="$4"

    local status_icon="${RED}○${NC}"
    local status_color="$RED"

    if [ "$count" -gt 0 ]; then
        status_icon="${GREEN}●${NC}"
        status_color="$GREEN"
    fi

    printf "${BOLD}${WHITE}║${NC}   %s %-20s %s ${status_color}%5d${NC} %-10s                      ${BOLD}${WHITE}║${NC}\n" "$status_icon" "$step: $name" "" "$count" "$unit"
}

# 최근 파일 활동 출력
print_recent_activity() {
    echo -e "${BOLD}${WHITE}╠$(printf '═%.0s' $(seq 1 $(($(tput cols)-2))))╣${NC}"
    echo -e "${BOLD}${WHITE}║${NC} ${BOLD}RECENT FILE ACTIVITY${NC} (last 5 min)                                    ${BOLD}${WHITE}║${NC}"

    local recent_files=$(find "$DATA_ROOT" -type f -mmin -5 2>/dev/null | head -5)

    if [ -n "$recent_files" ]; then
        echo "$recent_files" | while read fpath; do
            local fname=$(basename "$fpath")
            local ftime=$(stat -c '%Y' "$fpath" 2>/dev/null)
            local ftime_fmt=$(date -d "@$ftime" '+%H:%M:%S' 2>/dev/null)
            printf "${BOLD}${WHITE}║${NC}   ${CYAN}%s${NC} %-55s ${BOLD}${WHITE}║${NC}\n" "$ftime_fmt" "${fname:0:55}"
        done
    else
        printf "${BOLD}${WHITE}║${NC}   ${DIM}No recent file activity${NC}                                           ${BOLD}${WHITE}║${NC}\n"
    fi
}

# API 상태 확인
print_api_status() {
    echo -e "${BOLD}${WHITE}╠$(printf '═%.0s' $(seq 1 $(($(tput cols)-2))))╣${NC}"
    echo -e "${BOLD}${WHITE}║${NC} ${BOLD}API HEALTH${NC}                                                            ${BOLD}${WHITE}║${NC}"

    local health=$(curl -s --max-time 2 "$API_URL/api/health" 2>/dev/null)

    if [ -n "$health" ]; then
        local status=$(echo "$health" | grep -oP '"status"\s*:\s*"\K[^"]+' 2>/dev/null || echo "unknown")
        if [ "$status" = "healthy" ]; then
            printf "${BOLD}${WHITE}║${NC}   ${GREEN}● API Healthy${NC}                                                       ${BOLD}${WHITE}║${NC}\n"
        else
            printf "${BOLD}${WHITE}║${NC}   ${YELLOW}● API Status: %s${NC}                                              ${BOLD}${WHITE}║${NC}\n" "$status"
        fi
    else
        printf "${BOLD}${WHITE}║${NC}   ${RED}● API Not Responding${NC} (server busy or down)                         ${BOLD}${WHITE}║${NC}\n"
    fi
}

# 푸터 출력
print_footer() {
    local cols=$(tput cols)
    echo -e "${BOLD}${WHITE}╠$(printf '═%.0s' $(seq 1 $((cols-2))))╣${NC}"
    echo -e "${BOLD}${WHITE}║${NC} ${DIM}[q] Quit  [r] Refresh  [s] Set source_id  [f] FAISS detail  [l] Logs${NC}  ${BOLD}${WHITE}║${NC}"
    echo -e "${BOLD}${WHITE}╚$(printf '═%.0s' $(seq 1 $((cols-2))))╝${NC}"
}

# 메인 화면 그리기
draw_screen() {
    local source_id="$1"
    clear_screen
    print_header
    print_system_status
    print_dataset_status "$source_id"
    print_recent_activity
    print_api_status
    print_footer
}

# 사용법 출력
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -s, --source-id ID    Monitor specific source_id"
    echo "  -i, --interval SEC    Refresh interval in seconds (default: 3)"
    echo "  -h, --help            Show this help"
    echo ""
    echo "Example:"
    echo "  $0 -s src_20260710_122653_eafb7a -i 5"
}

# 메인 루프
main() {
    local source_id=""
    local interval=3

    # 인자 파싱
    while [[ $# -gt 0 ]]; do
        case $1 in
            -s|--source-id)
                source_id="$2"
                shift 2
                ;;
            -i|--interval)
                interval="$2"
                shift 2
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                shift
                ;;
        esac
    done

    # 터미널 설정
    trap 'tput cnorm; exit 0' INT TERM
    tput civis  # 커서 숨기기

    while true; do
        draw_screen "$source_id"

        # 비동기 키 입력 처리
        read -t $interval -n 1 key 2>/dev/null
        case $key in
            q|Q)
                tput cnorm
                clear
                echo "Exiting monitor..."
                exit 0
                ;;
            r|R)
                continue
                ;;
            s|S)
                tput cnorm
                echo -en "\n${CYAN}Enter source_id: ${NC}"
                read new_source_id
                source_id="$new_source_id"
                tput civis
                ;;
            f|F)
                tput cnorm
                echo -e "\n${CYAN}FAISS Index Details:${NC}"
                ls -lah "$DATA_ROOT/indexes/faiss/" 2>/dev/null | tail -20
                echo -e "\n${DIM}Press any key to continue...${NC}"
                read -n 1
                tput civis
                ;;
            l|L)
                tput cnorm
                echo -e "\n${CYAN}Recent Logs:${NC}"
                tail -30 /data/weeslee/weeslee-rag/logs/uvicorn*.log 2>/dev/null || echo "No logs found"
                echo -e "\n${DIM}Press any key to continue...${NC}"
                read -n 1
                tput civis
                ;;
        esac
    done
}

main "$@"
