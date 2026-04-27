# 2026-04-27 Metadata Quality Fix Result

## 1. Issue

The HWPX validation run initially produced incorrect metadata for the real RFP:

- wrong title
- wrong document type
- wrong category fallback to `기타`

This made the quality check unreliable.

## 2. Fix Applied

### 2.1 Metadata extractor

- Added deterministic HWPX/RFP title hints
- Preserved `RFP` classification instead of letting validation logic demote it to `기타`
- Added RFP-related keyword enrichment

### 2.2 Validation script

- Switched output files to unique per-process names
- Kept validation failures visible instead of hiding them

## 3. Final Result

After the fix, the same real HWPX RFP now reports:

- `title`: `AX 기반의 차세대 업무시스템 구축을 위한 ISMP 제안요청서`
- `category`: `RFP`
- `document_type`: `RFP`
- `keywords`: include `제안요청서`, `ISMP`, `차세대`, `업무시스템`

## 4. Retrieval Result

The retrieval test still recommends relevant proposal documents first:

1. `DOC-20260427-000010` `presentation`
2. `DOC-20260427-000007` `proposal`
3. `DOC-20260427-000024` `final_report`
4. `DOC-20260427-000017` `proposal`
5. `DOC-20260427-000019` `final_report`

## 5. Conclusion

The metadata quality issue is resolved for the real HWPX RFP validation path.
The remaining improvement area is retrieval reranking, not metadata classification.
