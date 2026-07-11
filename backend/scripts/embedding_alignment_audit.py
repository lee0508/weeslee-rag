# -*- coding: utf-8 -*-
"""
임베딩 정렬 감사 스크립트 (2026-07-09)

검사 항목:
1. FAISS 벡터 ↔ 청크 저장소 인덱스 정합 (self-hit 검사)
2. Ollama 임베딩 silent truncation 검사

사용법:
    python backend/scripts/embedding_alignment_audit.py --check-alignment
    python backend/scripts/embedding_alignment_audit.py --check-truncation
    python backend/scripts/embedding_alignment_audit.py --all
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import httpx
import numpy as np

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OLLAMA_HOST = "http://127.0.0.1:11434"
EMBEDDING_MODEL = "bge-m3:8k"  # num_ctx=8192 설정된 모델


def load_faiss_index(snapshot_id: str):
    """FAISS 인덱스 로드"""
    try:
        import faiss
    except ImportError:
        print("❌ faiss 패키지가 설치되지 않았습니다.")
        return None

    index_path = DATA_DIR / "indexes" / "faiss" / f"{snapshot_id}_ollama.index"
    if not index_path.exists():
        print(f"❌ 인덱스 파일 없음: {index_path}")
        return None

    return faiss.read_index(str(index_path))


def load_metadata(snapshot_id: str) -> list[dict]:
    """메타데이터 JSONL 로드"""
    meta_path = DATA_DIR / "indexes" / "faiss" / f"{snapshot_id}_ollama_metadata.jsonl"
    if not meta_path.exists():
        print(f"❌ 메타데이터 파일 없음: {meta_path}")
        return []

    rows = []
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_chunks(snapshot_id: str) -> dict[str, str]:
    """청크 JSONL 로드 (chunk_id → text 매핑)"""
    chunk_path = DATA_DIR / "staged" / "chunks" / f"{snapshot_id}_chunks.jsonl"
    if not chunk_path.exists():
        print(f"❌ 청크 파일 없음: {chunk_path}")
        return {}

    mapping = {}
    for line in chunk_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            chunk_id = row.get("chunk_id")
            text = row.get("text") or row.get("embedding_text") or ""
            if chunk_id:
                mapping[chunk_id] = text
    return mapping


def embed_text_ollama(text: str) -> list[float] | None:
    """Ollama를 통해 텍스트 임베딩"""
    try:
        resp = httpx.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json().get("embedding")
    except Exception as e:
        print(f"⚠️ 임베딩 실패: {e}")
        return None


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """코사인 유사도 계산"""
    a = np.array(v1)
    b = np.array(v2)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def check_alignment(snapshot_id: str, sample_size: int = 50):
    """
    검사1+2: FAISS ↔ 청크 저장소 왕복 정합 검사

    청크 원문을 다시 임베딩해서 FAISS에서 검색했을 때
    자기 자신이 1위(self-hit)로 나오는지 확인
    """
    print("\n" + "=" * 60)
    print("검사1+2: FAISS ↔ 청크 저장소 왕복 정합 검사")
    print("=" * 60)

    index = load_faiss_index(snapshot_id)
    if index is None:
        return

    metadata = load_metadata(snapshot_id)
    chunks = load_chunks(snapshot_id)

    if not metadata or not chunks:
        print("❌ 메타데이터 또는 청크 데이터가 없습니다.")
        return

    print(f"📊 FAISS 벡터 수: {index.ntotal}")
    print(f"📊 메타데이터 행 수: {len(metadata)}")
    print(f"📊 청크 수: {len(chunks)}")

    # 기본 정합성 확인
    if index.ntotal != len(metadata):
        print(f"❌ FAISS 벡터 수({index.ntotal})와 메타데이터 행 수({len(metadata)})가 불일치합니다!")
        print("   → 인덱스-저장소 어긋남 확정. 전체 재색인 필요.")
        return

    # 샘플 추출하여 self-hit 검사
    sample_indices = random.sample(range(len(metadata)), min(sample_size, len(metadata)))
    self_hits = 0
    top3_hits = 0
    failures = []

    print(f"\n🔍 {len(sample_indices)}개 샘플에 대해 self-hit 검사 진행...")

    for i, idx in enumerate(sample_indices):
        meta = metadata[idx]
        chunk_id = meta.get("chunk_id")
        text = chunks.get(chunk_id, "")

        if not text:
            print(f"⚠️ [{i+1}/{len(sample_indices)}] chunk_id={chunk_id} 텍스트 없음")
            continue

        # 텍스트 재임베딩
        embedding = embed_text_ollama(text[:2000])  # 너무 긴 텍스트는 잘라서 테스트
        if embedding is None:
            continue

        # FAISS 검색
        query_vec = np.array([embedding], dtype=np.float32)
        distances, indices = index.search(query_vec, 5)

        # self-hit 확인
        if indices[0][0] == idx:
            self_hits += 1
        if idx in indices[0][:3]:
            top3_hits += 1
        else:
            failures.append({
                "idx": idx,
                "chunk_id": chunk_id,
                "text_preview": text[:100],
                "found_indices": indices[0].tolist(),
            })

        if (i + 1) % 10 == 0:
            print(f"  진행: {i+1}/{len(sample_indices)} (self-hit: {self_hits})")

    # 결과 출력
    print("\n" + "-" * 60)
    print("📋 검사 결과")
    print("-" * 60)
    print(f"  샘플 수: {len(sample_indices)}")
    print(f"  Self-hit (1위): {self_hits} ({self_hits/len(sample_indices)*100:.1f}%)")
    print(f"  Top-3 hit: {top3_hits} ({top3_hits/len(sample_indices)*100:.1f}%)")

    if self_hits / len(sample_indices) < 0.95:
        print("\n❌ Self-hit 비율이 95% 미만입니다!")
        print("   → 원인: 인덱스-저장소 어긋남 또는 임베딩 모델 혼합")
        print("   → 조치: 전체 재색인 필요")
        if failures:
            print(f"\n   실패 샘플 (최대 5개):")
            for f in failures[:5]:
                print(f"     - idx={f['idx']}, chunk_id={f['chunk_id']}")
                print(f"       텍스트: {f['text_preview'][:50]}...")
                print(f"       검색 결과: {f['found_indices']}")
    else:
        print("\n✅ 왕복 정합 검사 통과 (self-hit ≥ 95%)")


def check_truncation(max_test_length: int = 4000, step: int = 500):
    """
    검사4: Ollama 임베딩 silent truncation 검사

    앞부분이 같고 뒷부분 의미가 정반대인 두 텍스트의 유사도를 측정하여
    어느 길이에서 truncation이 발생하는지 확인
    """
    print("\n" + "=" * 60)
    print("검사4: Ollama 임베딩 Silent Truncation 검사")
    print("=" * 60)

    # 테스트 텍스트 생성
    base_text = "정보시스템 구축 사업의 성공적인 추진을 위해 다음 사항을 고려해야 합니다. " * 50
    suffix_positive = " 이 사업은 매우 성공적이며 모든 목표를 달성했습니다."
    suffix_negative = " 이 사업은 완전히 실패했으며 모든 목표를 달성하지 못했습니다."

    print(f"\n📏 테스트 범위: 500자 ~ {max_test_length}자 (step={step})")
    print("   방법: 앞부분 동일 + 뒷부분 의미 정반대 → 유사도 비교")
    print("   기대: 정상이면 유사도 < 0.95, truncation 발생 시 유사도 ≈ 1.0\n")

    truncation_detected = None
    results = []

    for length in range(500, max_test_length + 1, step):
        text_a = base_text[:length] + suffix_positive
        text_b = base_text[:length] + suffix_negative

        emb_a = embed_text_ollama(text_a)
        emb_b = embed_text_ollama(text_b)

        if emb_a is None or emb_b is None:
            print(f"  {length}자: 임베딩 실패")
            continue

        sim = cosine_similarity(emb_a, emb_b)
        results.append({"length": length, "similarity": sim})

        status = "🔴 TRUNCATION!" if sim > 0.98 else "🟢 OK"
        print(f"  {length}자: 유사도 = {sim:.4f} {status}")

        if sim > 0.98 and truncation_detected is None:
            truncation_detected = length

    print("\n" + "-" * 60)
    print("📋 검사 결과")
    print("-" * 60)

    if truncation_detected:
        print(f"❌ Silent Truncation 감지됨!")
        print(f"   → 발생 지점: ~{truncation_detected}자")
        print(f"   → 원인: Ollama num_ctx 설정이 텍스트 길이보다 작음")
        print(f"   → 조치: chunk_size를 {truncation_detected - 200}자 이하로 설정하거나")
        print(f"           Ollama Modelfile에서 num_ctx를 증가시키세요.")
    else:
        print(f"✅ {max_test_length}자까지 truncation 미감지")
        print(f"   → 현재 chunk_size 설정이 안전합니다.")

    return results


def check_ollama_config():
    """Ollama 모델 설정 확인"""
    print("\n" + "=" * 60)
    print("Ollama 모델 설정 확인")
    print("=" * 60)

    try:
        resp = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=10.0)
        resp.raise_for_status()
        models = resp.json().get("models", [])

        target = None
        for m in models:
            if m.get("name") == EMBEDDING_MODEL or m.get("name", "").startswith("bge-m3"):
                target = m
                break

        if target:
            print(f"  모델: {target.get('name')}")
            print(f"  크기: {target.get('size', 0) / 1e9:.2f} GB")
            details = target.get("details", {})
            print(f"  파라미터: {details.get('parameter_size', 'N/A')}")
            print(f"  양자화: {details.get('quantization_level', 'N/A')}")
        else:
            print(f"⚠️ {EMBEDDING_MODEL} 모델을 찾을 수 없습니다.")

        # num_ctx 확인 (show API)
        resp2 = httpx.post(
            f"{OLLAMA_HOST}/api/show",
            json={"name": EMBEDDING_MODEL},
            timeout=10.0,
        )
        if resp2.status_code == 200:
            info = resp2.json()
            params = info.get("parameters", "")
            if "num_ctx" in params:
                print(f"  num_ctx 설정: {params}")
            else:
                print(f"  num_ctx: (기본값, 명시적 설정 없음)")
                print(f"  ⚠️ 기본 num_ctx는 모델마다 다르며, 보통 2048~4096입니다.")
    except Exception as e:
        print(f"⚠️ Ollama 정보 조회 실패: {e}")


def get_active_snapshot() -> str:
    """활성 스냅샷 ID 조회"""
    try:
        resp = httpx.get("http://127.0.0.1:8080/api/admin/faiss/status", timeout=10.0)
        resp.raise_for_status()
        return resp.json().get("snapshot_id", "")
    except Exception:
        # 파일에서 직접 조회
        active_file = DATA_DIR / "active_snapshot.txt"
        if active_file.exists():
            return active_file.read_text().strip()
        return ""


def main():
    parser = argparse.ArgumentParser(description="임베딩 정렬 감사 스크립트")
    parser.add_argument("--check-alignment", action="store_true", help="FAISS-청크 왕복 정합 검사")
    parser.add_argument("--check-truncation", action="store_true", help="Ollama silent truncation 검사")
    parser.add_argument("--all", action="store_true", help="모든 검사 실행")
    parser.add_argument("--snapshot", default=None, help="스냅샷 ID (기본: 활성 스냅샷)")
    parser.add_argument("--sample-size", type=int, default=50, help="self-hit 검사 샘플 수")
    args = parser.parse_args()

    snapshot_id = args.snapshot or get_active_snapshot()
    print(f"🎯 대상 스냅샷: {snapshot_id}")

    check_ollama_config()

    if args.all or args.check_truncation:
        check_truncation()

    if args.all or args.check_alignment:
        check_alignment(snapshot_id, sample_size=args.sample_size)

    if not args.all and not args.check_alignment and not args.check_truncation:
        print("\n사용법:")
        print("  --check-alignment : FAISS-청크 왕복 정합 검사")
        print("  --check-truncation: Ollama silent truncation 검사")
        print("  --all             : 모든 검사 실행")


if __name__ == "__main__":
    main()
