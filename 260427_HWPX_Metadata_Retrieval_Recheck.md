# 2026-04-27 HWPX Metadata and Retrieval Recheck

## 1. Test Target

- File: `data/raw/snapshot_2026-04-27/domestic_business/202603. AX기반의 차세대 업무 시스템 구축을 위한 ISMP/00. RFP/1. 제안요청서.hwpx`
- Extractor: `HwpxExtractor`
- Result: `success = true`
- Extracted length: `64677`

## 2. Metadata Summary

Because `metadata_extractor.py` is not present on the server snapshot, the validation run used a heuristic fallback.

Captured metadata:

- `title`: `AX 기반의 차세대 업무시스템 구축을 위한 ISMP 제안요청서`
- `category`: `RFP`
- `document_type`: `RFP`
- `keywords`: `RFP`, `제안요청서`, `ISMP`, `차세대`, `업무시스템`, `프로젝트`, `일정관리`, `보안요구사항`, `산출물`, `지적재산권`

## 3. Retrieval Result

The rerun used the extracted HWPX text to form a query and then searched the existing FAISS index.

Top 5 documents:

1. `DOC-20260427-000007` `proposal`
2. `DOC-20260427-000010` `presentation`
3. `DOC-20260427-000024` `final_report`
4. `DOC-20260427-000017` `proposal`
5. `DOC-20260427-000019` `final_report`

## 4. Assessment

### Good

1. The target RFP itself is being extracted correctly from HWPX.
2. Proposal documents still rank at the top.
3. The generated draft answer is aligned with the RFP theme.

### Needs Improvement

1. The server snapshot does not contain the full metadata extractor module, so metadata is currently heuristic only.
2. A non-relevant final report appeared at rank 3, which suggests document-level reranking still needs tighter filtering.
3. Query construction should be more focused on requirement phrases, not just title and keywords.

## 5. Conclusion

The HWPX extraction path is operational and useful for retrieval validation.
The current retrieval quality is acceptable for phase 1, but document-level reranking and metadata normalization still need work before production use.
