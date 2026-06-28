# Dataset Builder 상태 확인 스크립트
"""
사용법:
    cd /data/weeslee/weeslee-rag/backend/databuilder
    python3 check_status.py
"""
import httpx

API_BASE = "http://localhost:8080"


def main():
    print("=" * 60)
    print("Dataset Builder 상태 확인")
    print("=" * 60)

    with httpx.Client(timeout=30) as client:
        # Step 4 상태 (Parse/Extract)
        print("\n[Step 4: 텍스트 추출]")
        try:
            resp = client.get(f"{API_BASE}/api/admin/dataset-builder/step4/stats", params={"source_id": "rag_source"})
            if resp.status_code == 200:
                data = resp.json()
                print(f"  총 문서: {data.get('total', 0)}")
                print(f"  완료: {data.get('done', 0)}")
                print(f"  실패: {data.get('failed', 0)}")
                print(f"  총 페이지: {data.get('total_pages', 0)}")
                print(f"  총 문자: {data.get('total_chars', 0):,}")
        except Exception as e:
            print(f"  오류: {e}")

        # Step 5 상태 (Chunk)
        print("\n[Step 5: 청킹]")
        try:
            resp = client.get(f"{API_BASE}/api/admin/dataset-builder/step5/stats")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  총 문서: {data.get('total_documents', 0)}")
                print(f"  청킹 완료: {data.get('chunked_documents', 0)}")
                print(f"  총 청크: {data.get('total_chunks', 0)}")
                print(f"  평균 청크/문서: {data.get('avg_chunks', 0):.1f}")
        except Exception as e:
            print(f"  오류: {e}")

        # Step 6 상태 (Embed)
        print("\n[Step 6: 임베딩]")
        try:
            resp = client.get(f"{API_BASE}/api/admin/dataset-builder/step6/stats")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  총 문서: {data.get('total_documents', 0)}")
                print(f"  임베딩 완료: {data.get('embedded_documents', 0)}")
                print(f"  총 임베딩: {data.get('total_embeddings', 0)}")
                print(f"  사용 모델: {', '.join(data.get('models_used', []))}")
        except Exception as e:
            print(f"  오류: {e}")

        # Step 7 상태 (FAISS)
        print("\n[Step 7: FAISS 인덱스]")
        try:
            resp = client.get(f"{API_BASE}/api/admin/dataset-builder/step7/stats")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  컬렉션 수: {data.get('total_collections', 0)}")
                print(f"  총 벡터: {data.get('total_vectors', 0)}")
                print(f"  총 문서: {data.get('total_documents', 0)}")
        except Exception as e:
            print(f"  오류: {e}")

        # FAISS 활성 인덱스
        print("\n[활성 FAISS 인덱스]")
        try:
            resp = client.get(f"{API_BASE}/api/admin/faiss/status")
            if resp.status_code == 200:
                data = resp.json()
                config = data.get("server_config", {})
                print(f"  활성 스냅샷: {config.get('active_snapshot') or '(없음)'}")
                print(f"  임베딩 모델: {config.get('embedding_model')}")
                print(f"  임베딩 차원: {config.get('embedding_dim')}")
        except Exception as e:
            print(f"  오류: {e}")

        # 시스템 상태
        print("\n[시스템 상태]")
        try:
            resp = client.get(f"{API_BASE}/api/health/all")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  전체: {data.get('status')}")
                for name, comp in data.get("components", {}).items():
                    status = comp.get("status", "unknown")
                    extra = ""
                    if name == "faiss":
                        extra = f" ({comp.get('chunk_count', 0)} chunks)"
                    elif name == "ollama":
                        extra = f" ({comp.get('model_count', 0)} models)"
                    print(f"  - {name}: {status}{extra}")
        except Exception as e:
            print(f"  오류: {e}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
