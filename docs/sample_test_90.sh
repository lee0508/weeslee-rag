#!/bin/bash
# Dataset Builder sample test: select files from mounted folders.
# Flow: 30 random files per folder -> DB mapping -> approve mapped docs -> run Step 4-7.
# This script intentionally does not run Step 1 Source Scan or Step 2 Metadata Auto,
# because those APIs can process more than the selected sample set.

set -e

API_BASE="https://server.weeslee.co.kr/weeslee-rag/api"
MOUNT_ROOT="/mnt/w2_project/00. RAG 소스"

# 파일 저장 경로
SAMPLE_FILES_JSON="sample_files.json"
SAMPLE_IDS_JSON="sample_ids.json"
SAMPLE_MAPPING_JSON="sample_mapping_report.json"
RFP_LIST=".sample_rfp_files.txt"
PROPOSAL_LIST=".sample_proposal_files.txt"
OUTPUT_LIST=".sample_output_files.txt"
ALL_LIST=".sample_all_files.txt"
ALL_DOCS_JSON=".sample_all_docs.json"

echo "==========================================="
echo "  Dataset Builder 샘플 테스트 (90개)"
echo "==========================================="

# 1. 인증
echo ""
echo "=== 1. 인증 ==="
TOKEN=$(curl -s -X POST "$API_BASE/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"weeslee12#$"}' | jq -r '.access_token')

if [ "$TOKEN" = "null" ] || [ -z "$TOKEN" ]; then
  echo "❌ 로그인 실패"
  exit 1
fi

echo "✅ 로그인 성공: ${TOKEN:0:20}..."

# 2. 현재 상태 확인
echo ""
echo "=== 2. 현재 DB 상태 확인 ==="
curl -s -X GET "$API_BASE/admin/dataset/status-summary" \
  -H "Authorization: Bearer $TOKEN" | jq '{
    total_documents,
    step3_reviewed,
    step4_parsed: .step4_total_documents,
    step5_chunked: .step5_total_chunks,
    step6_embedded: .step6_total_embeddings,
    step7_indexed: .step7_total_vectors
  }'

# 3. 마운트 폴더에서 직접 파일 선택
echo ""
echo "=== 3. 마운트 폴더에서 파일 직접 선택 ==="

# 지원 파일 확장자
find_supported_files() {
  local folder="$1"
  find "$folder" -type f \( \
    -iname '*.hwp' -o \
    -iname '*.hwpx' -o \
    -iname '*.pdf' -o \
    -iname '*.pptx' -o \
    -iname '*.ppt' -o \
    -iname '*.docx' -o \
    -iname '*.doc' -o \
    -iname '*.xlsx' -o \
    -iname '*.xls' \
  \)
}

echo "📁 RFP 폴더 (01. RFP)에서 30개 무작위 선택..."
RFP_FOLDER="$MOUNT_ROOT/01. RFP"
if [ ! -d "$RFP_FOLDER" ]; then
  echo "❌ RFP 폴더가 존재하지 않습니다: $RFP_FOLDER"
  exit 1
fi

find_supported_files "$RFP_FOLDER" | shuf -n 30 > "$RFP_LIST"
RFP_COUNT=$(grep -c . "$RFP_LIST" || true)
echo "   선택됨: $RFP_COUNT 개"

echo "📁 제안서 폴더 (02. 제안서)에서 30개 무작위 선택..."
PROPOSAL_FOLDER="$MOUNT_ROOT/02. 제안서"
if [ ! -d "$PROPOSAL_FOLDER" ]; then
  echo "❌ 제안서 폴더가 존재하지 않습니다: $PROPOSAL_FOLDER"
  exit 1
fi

find_supported_files "$PROPOSAL_FOLDER" | shuf -n 30 > "$PROPOSAL_LIST"
PROPOSAL_COUNT=$(grep -c . "$PROPOSAL_LIST" || true)
echo "   선택됨: $PROPOSAL_COUNT 개"

echo "📁 산출물 폴더 (03. 산출물)에서 30개 무작위 선택..."
OUTPUT_FOLDER="$MOUNT_ROOT/03. 산출물"
if [ ! -d "$OUTPUT_FOLDER" ]; then
  echo "❌ 산출물 폴더가 존재하지 않습니다: $OUTPUT_FOLDER"
  exit 1
fi

find_supported_files "$OUTPUT_FOLDER" | shuf -n 30 > "$OUTPUT_LIST"
OUTPUT_COUNT=$(grep -c . "$OUTPUT_LIST" || true)
echo "   선택됨: $OUTPUT_COUNT 개"

# 4. 선택된 파일 목록 저장
echo ""
echo "=== 4. 선택된 파일 목록 저장 ==="

cat "$RFP_LIST" "$PROPOSAL_LIST" "$OUTPUT_LIST" > "$ALL_LIST"
TOTAL_FILES=$(grep -c . "$ALL_LIST" || true)

# JSON 배열로 저장
jq -R -s 'split("\n") | map(select(length > 0))' "$ALL_LIST" > "$SAMPLE_FILES_JSON"

echo "✅ 선택된 파일 $TOTAL_FILES 개를 $SAMPLE_FILES_JSON 에 저장"
echo "   - RFP: $RFP_COUNT 개"
echo "   - 제안서: $PROPOSAL_COUNT 개"
echo "   - 산출물: $OUTPUT_COUNT 개"

# 5. 선택 파일을 기존 DB 문서에 매핑
echo ""
echo "=== 5. 파일 경로 → document_id 매핑 ==="
echo "주의: Step 1 Source Scan과 Step 2 Metadata Auto는 샘플 범위를 벗어날 수 있어 실행하지 않습니다."

# DB에서 문서 조회. backend limit 최대값은 1000이다.
ALL_DOCS=$(curl -s -G "$API_BASE/admin/metadata-review/documents" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "limit=1000")

if ! echo "$ALL_DOCS" | jq -e 'has("documents") and (.documents | type == "array")' >/dev/null; then
  echo "❌ 문서 목록 API 응답에 documents 배열이 없습니다."
  echo "$ALL_DOCS" | jq '.'
  exit 1
fi

echo "$ALL_DOCS" > "$ALL_DOCS_JSON"

MAPPING_REPORT=$(jq -n \
  --slurpfile all_docs "$ALL_DOCS_JSON" \
  --slurpfile sample_files "$SAMPLE_FILES_JSON" \
  '
  $all_docs[0].documents as $docs |
  $sample_files[0] as $files |
  {
    matched: [
      $files[] as $file |
      ($docs[] | select(.file_path == $file)) as $doc |
      {
        file_path: $file,
        document_id: $doc.document_id,
        source_id: $doc.source_id,
        meta_status: $doc.meta_status,
        file_name: $doc.file_name
      }
    ],
    unmatched: [
      $files[] as $file |
      select(any($docs[]; .file_path == $file) | not) |
      $file
    ]
  }
  ')

echo "$MAPPING_REPORT" > "$SAMPLE_MAPPING_JSON"

MATCHED_IDS=$(echo "$MAPPING_REPORT" | jq '[.matched[].document_id] | unique')

MATCHED_COUNT=$(echo "$MATCHED_IDS" | jq 'length')
UNMATCHED_COUNT=$(echo "$MAPPING_REPORT" | jq '.unmatched | length')

echo "✅ 매칭된 document_id: $MATCHED_COUNT 개"
echo "⚠️  DB 미매칭 파일: $UNMATCHED_COUNT 개"
echo "   매핑 리포트: $SAMPLE_MAPPING_JSON"

if [ "$MATCHED_COUNT" -eq 0 ]; then
  echo "❌ 선택된 파일 중 DB에 매칭되는 문서가 없습니다."
  echo "   먼저 별도 Source Scan 작업으로 문서를 등록한 뒤 다시 시도하세요."
  exit 1
fi

# sample_ids.json 저장
echo "$MATCHED_IDS" > "$SAMPLE_IDS_JSON"
echo "✅ document_id 목록을 $SAMPLE_IDS_JSON 에 저장"

# 6. Step 3: Metadata Review (매핑된 샘플 문서 승인)
echo ""
echo "=== 6. Step 3: Metadata Review (샘플 문서 일괄 승인) ==="

STEP3_RESULT=$(curl -s -X POST "$API_BASE/admin/metadata-review/approve" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"document_ids\": $MATCHED_IDS, \"reviewer\": \"admin\"}")

echo "$STEP3_RESULT" | jq '{success, approved_count, total_requested, failed_ids}'

echo ""
echo "Step 3 완료. 5초 후 Step 4 시작..."
sleep 5

# 7. Step 4: OCR/Parser
echo ""
echo "=== 7. Step 4: OCR/Parser ($MATCHED_COUNT docs) ==="
STEP4_START=$(date +%s)

STEP4_RESULT=$(curl -s -X POST "$API_BASE/admin/dataset-builder/step4/parse" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"document_ids\": $MATCHED_IDS, \"force_reparse\": false}")

echo "$STEP4_RESULT" | jq '{success, total_documents, processed, failed, skipped, processing_time}'

STEP4_END=$(date +%s)
STEP4_DURATION=$((STEP4_END - STEP4_START))
echo "   실제 소요 시간: ${STEP4_DURATION}초"

# 8. Step 5: Chunk Build
echo ""
echo "=== 8. Step 5: Chunk Build ($MATCHED_COUNT docs) ==="
STEP5_START=$(date +%s)

STEP5_RESULT=$(curl -s -X POST "$API_BASE/admin/dataset-builder/step5/chunk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"document_ids\": $MATCHED_IDS, \"chunk_size\": 512, \"chunk_overlap\": 50, \"force_rebuild\": false}")

echo "$STEP5_RESULT" | jq '{success, processed, failed, skipped, total_chunks, chunk_size, chunk_overlap}'

STEP5_END=$(date +%s)
STEP5_DURATION=$((STEP5_END - STEP5_START))
echo "   실제 소요 시간: ${STEP5_DURATION}초"

# 9. Step 6: Embedding Build
echo ""
echo "=== 9. Step 6: Embedding Build ($MATCHED_COUNT docs) ==="
STEP6_START=$(date +%s)

STEP6_RESULT=$(curl -s -X POST "$API_BASE/admin/dataset-builder/step6/embed" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"document_ids\": $MATCHED_IDS, \"model\": \"nomic-embed-text\", \"batch_size\": 32, \"force_rebuild\": false}")

echo "$STEP6_RESULT" | jq '{success, processed, failed, skipped, total_embeddings, model, embedding_dim}'

STEP6_END=$(date +%s)
STEP6_DURATION=$((STEP6_END - STEP6_START))
echo "   실제 소요 시간: ${STEP6_DURATION}초"

# 10. Step 7: FAISS Build
echo ""
echo "=== 10. Step 7: FAISS Build ($MATCHED_COUNT docs) ==="
STEP7_START=$(date +%s)

COLLECTION_NAME="sample_${MATCHED_COUNT}_$(date +%Y%m%d_%H%M%S)"

STEP7_RESULT=$(curl -s -X POST "$API_BASE/admin/dataset-builder/step7/build" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"collection_name\": \"$COLLECTION_NAME\", \"document_ids\": $MATCHED_IDS, \"index_type\": \"flat\", \"metric\": \"l2\", \"normalize\": true}")

echo "$STEP7_RESULT" | jq '{success, collection_name, total_vectors, embedding_dim, documents_indexed, index_type}'

STEP7_END=$(date +%s)
STEP7_DURATION=$((STEP7_END - STEP7_START))
echo "   실제 소요 시간: ${STEP7_DURATION}초"

# 11. Step 10: Search Quality Test
echo ""
echo "=== 11. Step 10: Search Quality Test ==="

STEP10_RESULT=$(curl -s -X POST "$API_BASE/admin/dataset-builder/step10/test" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "test_queries": [
      {"query": "ISP 방법론", "category": "proposal"},
      {"query": "클라우드 마이그레이션"},
      {"query": "디지털 전환 전략"},
      {"query": "한국수자원공사 사업"}
    ],
    "top_k": 10,
    "use_graph": false
  }')

echo "$STEP10_RESULT" | jq '{success, total_queries, passed_queries, failed_queries, avg_search_time_ms}'

# 14. 최종 요약
TOTAL_DURATION=$((STEP4_DURATION + STEP5_DURATION + STEP6_DURATION + STEP7_DURATION))

echo ""
echo "==========================================="

rm -f "$RFP_LIST" "$PROPOSAL_LIST" "$OUTPUT_LIST" "$ALL_LIST" "$ALL_DOCS_JSON"
echo "           샘플 테스트 완료"
echo "==========================================="
echo "마운트 폴더에서 선택: $TOTAL_FILES 개"
echo "  - RFP: $RFP_COUNT 개"
echo "  - 제안서: $PROPOSAL_COUNT 개"
echo "  - 산출물: $OUTPUT_COUNT 개"
echo ""
echo "DB 매칭 성공: $MATCHED_COUNT 개"
echo ""
echo "소요 시간:"
echo "  - Step 4 (OCR):      ${STEP4_DURATION}초"
echo "  - Step 5 (Chunk):    ${STEP5_DURATION}초"
echo "  - Step 6 (Embed):    ${STEP6_DURATION}초"
echo "  - Step 7 (FAISS):    ${STEP7_DURATION}초"
echo "  - 총 시간:           ${TOTAL_DURATION}초"
echo ""
echo "생성 파일:"
echo "  - $SAMPLE_FILES_JSON  (선택된 파일 경로)"
echo "  - $SAMPLE_IDS_JSON    (매칭된 document_id)"
echo "  - $SAMPLE_MAPPING_JSON (파일 경로와 DB 매핑 결과)"
echo ""
echo "생성된 FAISS 컬렉션: $COLLECTION_NAME"
echo "==========================================="
