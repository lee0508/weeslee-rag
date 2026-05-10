# 2026-04-27 Metadata Quality Checklist

## 1. Purpose

Verify that extracted metadata is good enough for retrieval, reranking, and proposal drafting.

## 2. Required Fields

- `title`
- `document_type`
- `category`
- `organization`
- `project_name`
- `year`
- `keywords`
- `summary`
- `confidence_score`

## 3. Quality Rules

### 3.1 Title

- Must reflect the actual document title
- Must not be just the filename unless no better signal exists

### 3.2 Document Type

- Real RFP source should be classified as `RFP`
- Proposal source should be classified as `proposal`
- Report source should be classified as `final_report` or a close equivalent

### 3.3 Organization and Project

- If the document clearly states the organization or project name, extract it
- Leave blank only when the signal is absent or ambiguous

### 3.4 Keywords

- Must include domain terms that help retrieval
- For this project, useful terms include:
  - `RFP`
  - `제안요청서`
  - `ISMP`
  - `차세대`
  - `업무시스템`
  - `프로젝트`
  - `일정관리`
  - `보안요구사항`
  - `산출물`
  - `지적재산권`

### 3.5 Confidence

- High-confidence extraction should be used for indexing without manual review
- Low-confidence extraction should be flagged for review

## 4. Validation Levels

1. `pass`
- Title, document type, and keywords are correct

2. `review`
- Metadata is usable but incomplete

3. `fail`
- Metadata is misleading or empty

## 5. Server Validation Scope

For each real HWPX RFP validation run, check:

- Extracted title matches the document
- RFP terms appear in keywords
- Document type is classified as `RFP`
- The top retrieved document remains proposal-oriented
- The generated answer stays grounded in the extracted RFP text

## 6. Next Action

Use this checklist together with the HWPX extraction validation script so extraction, metadata, retrieval, and generation are verified together.
