# 2026-04-27 HWPX Extraction Result Schema

## 1. Purpose

Define a stable output format for HWPX extraction so downstream processing in `weeslee-rag` can consume it consistently.

This schema has two layers:

1. Raw extractor result
2. Normalized metadata result

## 2. Raw Extraction Result Schema

The format below matches the return value of `backend/app/extractors/hwpx_extractor.py`.

```json
{
  "success": true,
  "content": "extracted body text",
  "metadata": {
    "source": "/path/to/file.hwpx",
    "filename": "file.hwpx",
    "preview_available": true,
    "sections": 12,
    "content_length": 18423
  },
  "error": null,
  "method": "hwpx-zip"
}
```

## 3. Field Definitions

- `success`
  - Extraction success flag

- `content`
  - Combined text from `Preview/PrvText.txt` and `Contents/section*.xml`

- `metadata.source`
  - Absolute input file path

- `metadata.filename`
  - File name

- `metadata.preview_available`
  - Whether `Preview/PrvText.txt` was present

- `metadata.sections`
  - Number of section XML files read

- `metadata.content_length`
  - Final extracted text length

- `method`
  - Always `hwpx-zip`

## 4. Recommended Normalized Metadata

For downstream indexing and retrieval, create a separate normalized record with fields like:

- `document_id`
- `source_path`
- `snapshot_path`
- `document_type`
- `project_name`
- `organization`
- `year`
- `stage`
- `title`
- `summary`
- `keywords`
- `section_titles`
- `requirement_terms`
- `risk_terms`
- `confidence_score`

## 5. Processing Rules

1. Use `Preview/PrvText.txt` first when available.
2. Use section XML files to enrich the main body text.
3. If the extracted text is too long, split it again during chunking.
4. Combine LLM metadata extraction with filename heuristics for `title`, `project_name`, and `organization`.
5. Treat HWPX as a primary RFP source, higher priority than downstream proposal documents.

## 6. Quality Checks

- Is the document title preserved?
- Are requirement sentences readable?
- Does the section count roughly match the actual document structure?
- Is the extracted text non-empty?
- Do the RFP keywords appear in metadata?

## 7. Next Step

Use this schema to re-extract a real HWPX RFP on the server, then feed the output into metadata extraction, reranking, and `RFP -> proposal` graph linking.
