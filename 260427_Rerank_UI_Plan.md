# 2026-04-27 Rerank and UI Plan

## 1. Current Need

The real HWPX validation path now works, but document-level reranking still needs to favor:

- `proposal`
- `rfp`
- `kickoff`

It should penalize unrelated `final_report` results when the query is clearly RFP-oriented.

## 2. Backend Changes

### 2.1 Reranking

- Expanded category intent detection
- Added document-type priority scoring
- Added a penalty for `final_report` in RFP-style queries

### 2.2 RAG API

- Added `POST /api/rag/query`
- The API wraps the document-level RAG assembly pipeline
- It returns ranked documents and a draft answer

## 3. Front End Changes

### 3.1 New Assistant Page

- Added `frontend/rag-assistant.html`
- This page is a dedicated RFP analysis and proposal drafting UI

### 3.2 Page Functions

- Submit an RFP query
- View ranked documents
- Inspect reasons and evidence snippets
- Read the draft answer from the LLM
- Check API / Ollama / VectorDB health
- Use the live backend directly at `http://192.168.0.207:8080/api`

## 4. Why This Is the Right Next Step

The project is not just a pipeline. It needs an analyst-facing interface that can:

- test real RFP queries
- explain why documents were selected
- support proposal drafting workflows

## 5. Next Step

Deploy the backend route and the new assistant page, then run one real query from the HWPX RFP to verify that the ordering is more proposal-oriented than before.

For the fast path, keep the assistant page fixed to the live backend on port `8080` and validate without adding a new nginx route yet.
