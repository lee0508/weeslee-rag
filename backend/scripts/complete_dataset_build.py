# 데이터셋 빌드 백그라운드 완료 스크립트 (source_id별 폴더 구조)
"""
서버에서 nohup으로 실행하여 Step 5/6/7을 백그라운드에서 완료
데이터는 data/source/{source_id}/step{N}/ 폴더에 저장

Usage: nohup python3 complete_dataset_build.py src_20260710_122653_eafb7a > /tmp/dataset_build.log 2>&1 &
"""
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/dataset_build_detail.log')
    ]
)
logger = logging.getLogger(__name__)

# 프로젝트 루트 설정
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
DATA_DIR = PROJECT_ROOT / "data"


def get_source_dir(source_id: str) -> Path:
    """source_id별 데이터 디렉토리"""
    return DATA_DIR / "source" / source_id


def get_source_documents(source_id: str) -> list:
    """source_id에 해당하는 문서 목록을 id_contract.json에서 조회"""
    docs = []
    documents_dir = DATA_DIR / "documents"

    if not documents_dir.exists():
        logger.error(f"documents 폴더가 없습니다: {documents_dir}")
        return docs

    for doc_dir in documents_dir.iterdir():
        if not doc_dir.is_dir():
            continue

        # id_contract.json에서 source_id 확인
        contract_file = doc_dir / "id_contract.json"
        if contract_file.exists():
            try:
                with open(contract_file, 'r', encoding='utf-8') as f:
                    contract = json.load(f)
                    if contract.get("source_id") == source_id:
                        doc_id = doc_dir.name
                        filename = Path(contract.get("relative_path", f"doc_{doc_id}")).name
                        docs.append({
                            "id": doc_id,
                            "filename": filename,
                            "doc_dir": str(doc_dir),
                            "relative_path": contract.get("relative_path", "")
                        })
            except Exception as e:
                logger.warning(f"id_contract.json 읽기 실패 {doc_dir}: {e}")

    logger.info(f"source_id={source_id}에서 {len(docs)}개 문서 발견")
    return sorted(docs, key=lambda x: x["id"])


def chunk_document(doc: dict, source_id: str, chunk_size: int = 512) -> dict:
    """단일 문서 청킹"""
    doc_id = doc["id"]
    filename = doc["filename"]
    doc_dir = Path(doc["doc_dir"])

    # source_id별 폴더에 저장
    source_dir = get_source_dir(source_id)
    step5_dir = source_dir / "step5_chunk"
    output_dir = step5_dir / str(doc_id)

    # 이미 청킹된 경우 스킵
    chunks_file = output_dir / "chunks.jsonl"
    if chunks_file.exists():
        with open(chunks_file, 'r', encoding='utf-8') as f:
            chunk_count = sum(1 for _ in f)
        return {"status": "skipped", "chunks": chunk_count}

    # OCR 텍스트 추출
    text = ""
    ocr_dir = doc_dir / "ocr"

    # 1. full_text 파일 시도 (원문 유지를 위해 .txt 우선)
    for candidate in ["full_text.txt", "full_text.md", "content.txt"]:
        text_file = ocr_dir / candidate
        if text_file.exists():
            try:
                with open(text_file, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
                if text.strip():
                    break
            except Exception as e:
                logger.warning(f"텍스트 파일 읽기 실패 {text_file}: {e}")

    # 2. structured_data.json 시도
    if not text.strip():
        struct_file = ocr_dir / "structured_data.json"
        if struct_file.exists():
            try:
                with open(struct_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if isinstance(data, dict):
                    if "full_text" in data:
                        text = data["full_text"]
                    elif "content" in data:
                        text = data["content"]
                    elif "text" in data:
                        text = data["text"]
                    elif "slides" in data:
                        for slide in data.get("slides", []):
                            if isinstance(slide, dict):
                                text += slide.get("text", "") + "\n"
                                text += slide.get("content", "") + "\n"
                    elif "pages" in data:
                        for page in data.get("pages", []):
                            if isinstance(page, dict):
                                text += page.get("text", "") + "\n"
            except Exception as e:
                logger.warning(f"structured_data.json 파싱 실패 {doc_id}: {e}")

    if not text.strip():
        return {"status": "error", "chunks": 0, "message": "no text"}

    # 청킹 (문단 기반)
    chunks = []
    paragraphs = text.split('\n\n')
    current_chunk = ""
    chunk_index = 0
    char_limit = chunk_size * 4

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) < char_limit:
            current_chunk += para + "\n\n"
        else:
            if current_chunk.strip():
                chunks.append({
                    "chunk_id": f"{doc_id}_{chunk_index}",
                    "document_id": doc_id,
                    "chunk_index": chunk_index,
                    "text": current_chunk.strip(),
                    "char_count": len(current_chunk.strip()),
                    "filename": filename,
                    "source_id": source_id
                })
                chunk_index += 1
            current_chunk = para + "\n\n"

    # 마지막 청크
    if current_chunk.strip():
        chunks.append({
            "chunk_id": f"{doc_id}_{chunk_index}",
            "document_id": doc_id,
            "chunk_index": chunk_index,
            "text": current_chunk.strip(),
            "char_count": len(current_chunk.strip()),
            "filename": filename,
            "source_id": source_id
        })

    # 청크가 없으면 전체를 하나로
    if not chunks and text.strip():
        chunks.append({
            "chunk_id": f"{doc_id}_0",
            "document_id": doc_id,
            "chunk_index": 0,
            "text": text.strip()[:char_limit],
            "char_count": min(len(text.strip()), char_limit),
            "filename": filename,
            "source_id": source_id
        })

    # 저장 (source_id 폴더)
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(chunks_file, 'w', encoding='utf-8') as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')

    # 저장 (documents 폴더 - 호환성)
    doc_chunk_dir = doc_dir / "chunk"
    doc_chunk_dir.mkdir(parents=True, exist_ok=True)
    with open(doc_chunk_dir / "chunks.jsonl", 'w', encoding='utf-8') as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')

    return {"status": "success", "chunks": len(chunks)}


def run_step5_chunking(source_id: str) -> dict:
    """Step 5: 청킹 실행"""
    logger.info(f"=== Step 5 Chunking 시작: {source_id} ===")

    source_dir = get_source_dir(source_id)
    step5_dir = source_dir / "step5_chunk"
    step5_dir.mkdir(parents=True, exist_ok=True)

    docs = get_source_documents(source_id)
    if not docs:
        return {"status": "error", "message": "no documents found", "success": 0, "error": 0, "total_chunks": 0}

    results = {"success": 0, "skipped": 0, "error": 0, "total_chunks": 0}

    for i, doc in enumerate(docs):
        try:
            result = chunk_document(doc, source_id)
            results[result["status"]] = results.get(result["status"], 0) + 1
            results["total_chunks"] += result.get("chunks", 0)

            if (i + 1) % 20 == 0:
                logger.info(f"Chunk Progress: {i+1}/{len(docs)} - success={results['success']}, skipped={results['skipped']}, error={results['error']}")
        except Exception as e:
            logger.error(f"Error chunking {doc['filename']}: {e}")
            results["error"] += 1

    # Step 5 완료 메타 저장
    meta_file = step5_dir / "step5_meta.json"
    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump({
            "source_id": source_id,
            "completed_at": datetime.now().isoformat(),
            "results": results
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"Step 5 완료: {results}")
    return results


def run_step6_embedding(source_id: str) -> dict:
    """Step 6: 임베딩 생성"""
    logger.info(f"=== Step 6 Embedding 시작: {source_id} ===")

    import requests

    # Ollama 연결 확인
    try:
        resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
        if resp.status_code != 200:
            return {"status": "error", "message": "Ollama not available"}
        logger.info("Ollama 연결 확인됨")
    except Exception as e:
        return {"status": "error", "message": f"Ollama connection failed: {e}"}

    source_dir = get_source_dir(source_id)
    step5_dir = source_dir / "step5_chunk"
    step6_dir = source_dir / "step6_embedding"
    step6_dir.mkdir(parents=True, exist_ok=True)

    docs = get_source_documents(source_id)
    results = {"success": 0, "skipped": 0, "error": 0, "total_embeddings": 0}

    for i, doc in enumerate(docs):
        doc_id = doc["id"]
        doc_dir = Path(doc["doc_dir"])

        # 청크 파일
        chunks_file = step5_dir / str(doc_id) / "chunks.jsonl"
        if not chunks_file.exists():
            chunks_file = doc_dir / "chunk" / "chunks.jsonl"

        # 임베딩 출력
        output_dir = step6_dir / str(doc_id)
        embeddings_file = output_dir / "embeddings.jsonl"

        if embeddings_file.exists():
            results["skipped"] += 1
            continue

        if not chunks_file.exists():
            results["error"] += 1
            continue

        try:
            chunks = []
            with open(chunks_file, 'r', encoding='utf-8') as f:
                for line in f:
                    chunks.append(json.loads(line))

            embeddings = []
            for chunk in chunks:
                text = chunk.get("text", "")[:2000]

                resp = requests.post(
                    "http://127.0.0.1:11434/api/embeddings",
                    json={"model": "bge-m3:latest", "prompt": text},
                    timeout=120
                )

                if resp.status_code == 200:
                    embedding = resp.json().get("embedding", [])
                    embeddings.append({
                        "chunk_id": chunk["chunk_id"],
                        "document_id": doc_id,
                        "embedding": embedding,
                        "dim": len(embedding),
                        "source_id": source_id
                    })

            output_dir.mkdir(parents=True, exist_ok=True)
            with open(embeddings_file, 'w', encoding='utf-8') as f:
                for emb in embeddings:
                    f.write(json.dumps(emb, ensure_ascii=False) + '\n')

            results["success"] += 1
            results["total_embeddings"] += len(embeddings)

            if (i + 1) % 20 == 0:
                logger.info(f"Embedding Progress: {i+1}/{len(docs)} - embeddings={results['total_embeddings']}")

        except Exception as e:
            logger.error(f"Error embedding {doc['filename']}: {e}")
            results["error"] += 1

    meta_file = step6_dir / "step6_meta.json"
    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump({
            "source_id": source_id,
            "completed_at": datetime.now().isoformat(),
            "results": results
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"Step 6 완료: {results}")
    return results


def run_step7_faiss(source_id: str) -> dict:
    """Step 7: FAISS 인덱스 빌드"""
    logger.info(f"=== Step 7 FAISS 시작: {source_id} ===")

    try:
        import numpy as np
        import faiss
    except ImportError as e:
        return {"status": "error", "message": f"faiss not installed: {e}"}

    source_dir = get_source_dir(source_id)
    step5_dir = source_dir / "step5_chunk"
    step6_dir = source_dir / "step6_embedding"
    step7_dir = source_dir / "step7_faiss"
    step7_dir.mkdir(parents=True, exist_ok=True)

    docs = get_source_documents(source_id)

    all_embeddings = []
    all_metadata = []

    for doc in docs:
        doc_id = doc["id"]

        embeddings_file = step6_dir / str(doc_id) / "embeddings.jsonl"
        chunks_file = step5_dir / str(doc_id) / "chunks.jsonl"

        if not embeddings_file.exists():
            continue

        chunks_map = {}
        if chunks_file.exists():
            with open(chunks_file, 'r', encoding='utf-8') as f:
                for line in f:
                    chunk = json.loads(line)
                    chunks_map[chunk["chunk_id"]] = chunk

        with open(embeddings_file, 'r', encoding='utf-8') as f:
            for line in f:
                data = json.loads(line)
                if data.get("embedding"):
                    all_embeddings.append(data["embedding"])
                    chunk_meta = chunks_map.get(data["chunk_id"], {})
                    all_metadata.append({
                        "chunk_id": data["chunk_id"],
                        "document_id": doc_id,
                        "text": chunk_meta.get("text", "")[:500],
                        "filename": doc["filename"],
                        "source_id": source_id
                    })

    if not all_embeddings:
        return {"status": "error", "message": "no embeddings found"}

    logger.info(f"총 {len(all_embeddings)}개 임베딩 로드됨")

    embeddings_array = np.array(all_embeddings, dtype=np.float32)
    dim = embeddings_array.shape[1]

    index = faiss.IndexFlatIP(dim)
    faiss.normalize_L2(embeddings_array)
    index.add(embeddings_array)

    # source_id 폴더에 저장
    faiss.write_index(index, str(step7_dir / "index.faiss"))

    with open(step7_dir / "metadata.jsonl", 'w', encoding='utf-8') as f:
        for meta in all_metadata:
            f.write(json.dumps(meta, ensure_ascii=False) + '\n')

    # 글로벌 indexes 폴더에도 저장
    snapshot_id = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{source_id}"
    global_snapshot_dir = DATA_DIR / "indexes" / "faiss" / snapshot_id
    global_snapshot_dir.mkdir(parents=True, exist_ok=True)

    faiss.write_index(index, str(global_snapshot_dir / "index.faiss"))
    with open(global_snapshot_dir / "metadata.jsonl", 'w', encoding='utf-8') as f:
        for meta in all_metadata:
            f.write(json.dumps(meta, ensure_ascii=False) + '\n')

    # active_index.json 업데이트
    active_index = {
        "snapshot_id": snapshot_id,
        "source_id": source_id,
        "vector_count": len(all_embeddings),
        "dimension": dim,
        "created_at": datetime.now().isoformat()
    }
    with open(DATA_DIR / "active_index.json", 'w', encoding='utf-8') as f:
        json.dump(active_index, f, ensure_ascii=False, indent=2)

    meta_file = step7_dir / "step7_meta.json"
    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump({
            "source_id": source_id,
            "snapshot_id": snapshot_id,
            "vector_count": len(all_embeddings),
            "dimension": dim,
            "completed_at": datetime.now().isoformat()
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"Step 7 완료: {len(all_embeddings)} vectors indexed, snapshot={snapshot_id}")
    return {"status": "success", "vectors": len(all_embeddings), "snapshot_id": snapshot_id}


def main():
    if len(sys.argv) < 2:
        print("Usage: python complete_dataset_build.py <source_id>")
        sys.exit(1)

    source_id = sys.argv[1]
    logger.info(f"========== 데이터셋 빌드 시작: {source_id} ==========")
    logger.info(f"PROJECT_ROOT: {PROJECT_ROOT}")
    logger.info(f"DATA_DIR: {DATA_DIR}")
    logger.info(f"SOURCE_DIR: {get_source_dir(source_id)}")
    start_time = time.time()

    source_dir = get_source_dir(source_id)
    source_dir.mkdir(parents=True, exist_ok=True)

    # Step 5: 청킹
    step5_result = run_step5_chunking(source_id)

    # Step 6: 임베딩
    step6_result = run_step6_embedding(source_id)

    # Step 7: FAISS
    step7_result = run_step7_faiss(source_id)

    elapsed = time.time() - start_time
    logger.info(f"========== 데이터셋 빌드 완료: {elapsed:.1f}초 ==========")

    result = {
        "source_id": source_id,
        "completed_at": datetime.now().isoformat(),
        "elapsed_seconds": elapsed,
        "step5": step5_result,
        "step6": step6_result,
        "step7": step7_result
    }

    result_file = source_dir / "build_result.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    jobs_result_file = DATA_DIR / "jobs" / f"complete_build_{source_id}.json"
    jobs_result_file.parent.mkdir(parents=True, exist_ok=True)
    with open(jobs_result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n" + "="*60)
    print(f"빌드 완료 결과 (저장 위치: {source_dir})")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("="*60)


if __name__ == "__main__":
    main()
