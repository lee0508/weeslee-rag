# 2026-04-27 Server Deployment Runbook

## 1. Purpose

Define a safe procedure for applying local `weeslee-rag` changes to the company server at `192.168.0.207` under `/data/weeslee/weeslee-rag`.

## 2. Preconditions

- SSH access to the server is available
- `/data/weeslee/weeslee-rag` exists
- The project virtual environment can be activated
- Raw document snapshots remain under `data/raw`

## 3. Deployment Order

### 3.1 Code Delivery

1. Commit local changes
2. Push to `origin/main`
3. Pull or checkout the target commit on the server

### 3.2 Server Directory Check

```bash
cd /data/weeslee/weeslee-rag
git status --short
git rev-parse HEAD
```

### 3.3 Runtime Check

```bash
source .venv/bin/activate
python --version
ollama list
```

### 3.4 HWPX Extraction Validation

1. Select one real HWPX RFP file
2. Run the new extractor
3. Confirm that `Preview/PrvText.txt` and `section*.xml` contribute text
4. Record failures if extraction does not work

### 3.5 Reindexing

1. Generate extracted text
2. Run chunking
3. Build embeddings
4. Rebuild FAISS
5. Run sample queries

## 4. Operating Rules

- Never overwrite original documents
- Keep generated artifacts under `data/staged` and `data/indexes`
- Store server-only secrets in `.env` or server environment variables
- Keep large artifacts off the root partition `/`

## 5. Validation Checklist

- Does HWPX extraction work?
- Does the extracted text contain the requirement statements?
- Is `document_type` classified as `RFP`?
- Does search rank relevant proposal documents near the top?
- Does the RAG answer reflect the actual requirements?

## 6. Next Actions

After server deployment:

1. Re-extract one HWPX RFP
2. Tune metadata
3. Revalidate retrieval quality
4. Update the document relationship graph
