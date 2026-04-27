# 2026-04-27 HWPX Quality Check

## Target

- File: `data/raw/snapshot_2026-04-27/domestic_business/202603. AX기반의 차세대 업무 시스템 구축을 위한 ISMP/00. RFP/1. 제안요청서.hwpx`

## Server Result

- Extractor: `HwpxExtractor`
- Method: `hwpx-zip`
- Success: `true`
- Preview available: `true`
- Section count: `1`
- Extracted content length: `64677`

## Observations

1. The title was recovered correctly.
2. The preview text was present and usable.
3. The extracted body contains the RFP intro and requirement content.
4. The extractor now works on the real server copy of the HWPX RFP.

## Sample Extracted Head

The extracted text begins with:

- `AX 기반의 차세대 업무시스템 구축을 위한 ISMP 제안요청서`
- `2026년 2월`
- `공정거래 준수 안내`

## Assessment

This is sufficient for the next pipeline stage:

- metadata extraction
- chunking
- reranking
- `RFP -> proposal` relation mapping

## Next Step

Re-run metadata extraction and retrieval scoring using this extracted HWPX text, then verify whether proposal documents remain the top recommendations.
