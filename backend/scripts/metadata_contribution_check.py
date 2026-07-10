#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# weeslee-rag 메타데이터 "구성 → 검색 기여 → Graph/Wiki 반영률" 통합 진단 스크립트
"""
===================================================================
 metadata_contribution_check.py
 weeslee-rag 메타데이터 "구성 → 검색 기여 → Graph/Wiki 반영률" 통합 진단
===================================================================

[목적]
  Metadata Build 완료 후 생성된 메타데이터가
    (A) 어떤 필드로 구성되어 있고 얼마나 채워졌는지
    (B) 검색(FAISS/하이브리드)에 어떤 경로로 얼마나 기여할 준비가 됐는지
    (C) Graph JSON 노드와 LLM Wiki 페이지에 실제로 몇 %나 반영됐는지
  를 한 번에 수치로 측정한다.

[사용 예]
  # source_id 지정 (권장)
  python metadata_contribution_check.py \
      --data-root /data/weeslee/weeslee-rag/data \
      --source-id src_20260710_111246_d478a8

  # JSON 리포트 저장
  python metadata_contribution_check.py \
      --data-root /data/weeslee/weeslee-rag/data \
      --source-id src_20260710_111246_d478a8 \
      --report-out /tmp/meta_contribution_report.json

[실제 디렉터리 구조 (2026-07-10 기준)]
  {data_root}/indexes/faiss/*_{source_id}_*_metadata.jsonl  : FAISS 청크 메타데이터
  {data_root}/indexes/graph/{source_id}/graph_nodes.jsonl   : Graph 노드
  {data_root}/indexes/graph/{source_id}/graph_edges.jsonl   : Graph 엣지
  {data_root}/wiki/{source_id}/projects/*.md                : Wiki 페이지
  {data_root}/snapshots/active_snapshot.json                : 활성 스냅샷 포인터

 @author  위즐리앤컴퍼니(주) 개발팀 / Claude
 @date    2026-07-10
===================================================================
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

# ------------------------------------------------------------------
# 0. 필드 정의 — "이 필드가 어디에 쓰이는가"를 코드에 명시한다.
# ------------------------------------------------------------------
FIELD_SPEC = [
    # (필드명, 소비처 목록, 설명)
    ("doc_type",          ["filter"],                    "rfp/proposal/deliverable 분류"),
    ("project_name",      ["filter", "graph", "wiki"],   "Project 노드 / project 위키"),
    ("organization",      ["graph", "wiki"],             "Organization 노드 / organization 위키"),
    ("year",              ["filter", "graph"],           "연도 필터 / 연도 연결"),
    ("technology",        ["graph", "wiki"],             "Technology 노드 / technology 위키"),
    ("methodology",       ["graph"],                     "Methodology 엣지"),
    ("keyword",           ["graph", "bonus"],            "Keyword 노드 / 검색 보너스"),
    ("keywords",          ["graph", "bonus"],            "복수형 표기 호환"),
    ("topic",             ["graph"],                     "Topic 노드(선택)"),
    ("requirement",       ["graph"],                     "Requirement 노드(선택)"),
    ("organization_type", ["bonus"],                     "하이브리드 소프트 힌트"),
    ("business_domain",   ["bonus"],                     "하이브리드 소프트 힌트"),
    ("tags",              ["bonus"],                     "태그 보너스"),
    ("section_path",      ["embed"],                     "브레드크럼 → 임베딩 텍스트 주입"),
    ("chunk_role",        ["filter"],                    "child/parent/table 등 역할 필터"),
    ("section_type",      ["filter"],                    "번호 접두어 사고 이력 필드"),
    ("document_group",    ["filter"],                    "번호 접두어 사고 이력 필드"),
]

# Graph/Wiki 생성 가능 여부(GO/NO-GO)를 가르는 최소 필드와 임계값
CRITICAL_ENTITY_FIELDS = ["organization", "technology"]
GO_THRESHOLD = 0.10   # 문서 단위 충족률 10% 미만이면 해당 산출물 생성 불가로 판정

# 메타 엔티티 값 → Graph 노드 타입 매핑
GRAPH_NODE_TYPE_MAP = {
    "project_name": ("project",),
    "organization": ("organization", "org"),
    "technology":   ("technology", "tech"),
    "methodology":  ("methodology",),
    "keyword":      ("keyword",),
    "keywords":     ("keyword",),
    "topic":        ("topic",),
    "requirement":  ("requirement",),
}

# Wiki 페이지 카테고리 매핑
WIKI_CATEGORY_MAP = {
    "project_name": ("project", "projects"),
    "organization": ("organization", "organizations", "org"),
    "technology":   ("technology", "technologies", "tech"),
}

# "02. 기술및기능" 류 원시 번호 접두어 검출 정규식
RAW_PREFIX_RE = re.compile(r"^\d+\.\s")


# ------------------------------------------------------------------
# 1. 유틸리티
# ------------------------------------------------------------------
def is_filled(v) -> bool:
    """필드가 '실질적으로' 채워졌는지 판정한다."""
    if v is None:
        return False
    if isinstance(v, str):
        s = v.strip().lower()
        return s not in ("", "unknown", "none", "null", "n/a", "없음", "-")
    if isinstance(v, (list, tuple, set, dict)):
        return len(v) > 0
    return True


def norm_key(s: str) -> str:
    """엔티티 값 비교용 정규화."""
    s = unicodedata.normalize("NFC", str(s))
    s = s.lower()
    s = re.sub(r"[\s\-_·./()\[\]{}'\"]+", "", s)
    return s


def iter_values(v):
    """필드 값을 개별 엔티티 값 단위로 순회한다."""
    if v is None:
        return
    if isinstance(v, (list, tuple, set)):
        for item in v:
            yield from iter_values(item)
    elif isinstance(v, str):
        for part in re.split(r"[,;/]|、", v):
            part = part.strip()
            if part and is_filled(part):
                yield part
    else:
        yield str(v)


# ------------------------------------------------------------------
# 2. source_id 기반 파일 탐색
# ------------------------------------------------------------------
def find_faiss_metadata(data_root: Path, source_id: str) -> list[Path]:
    """source_id와 매칭되는 FAISS 메타데이터 JSONL 파일들을 찾는다."""
    faiss_dir = data_root / "indexes" / "faiss"
    if not faiss_dir.is_dir():
        return []

    # 패턴: *_{source_id}_*_metadata.jsonl 또는 *{source_id}*_metadata.jsonl
    matches = []
    for f in faiss_dir.glob("*_metadata.jsonl"):
        if source_id in f.name:
            matches.append(f)

    # 매칭되는 파일이 없으면 전체 JSONL 중 최신 것 사용 (폴백)
    if not matches:
        all_jsonl = sorted(faiss_dir.glob("*_metadata.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True)
        if all_jsonl:
            print(f"[경고] source_id '{source_id}' 매칭 파일 없음. 최신 파일 사용: {all_jsonl[0].name}")
            matches = [all_jsonl[0]]

    return matches


def find_graph_files(data_root: Path, source_id: str) -> tuple[Path | None, Path | None]:
    """source_id에 해당하는 Graph 노드/엣지 파일을 찾는다."""
    graph_dir = data_root / "indexes" / "graph" / source_id

    nodes_file = None
    edges_file = None

    if graph_dir.is_dir():
        nodes_path = graph_dir / "graph_nodes.jsonl"
        edges_path = graph_dir / "graph_edges.jsonl"
        if nodes_path.is_file():
            nodes_file = nodes_path
        if edges_path.is_file():
            edges_file = edges_path

    # 폴백: 루트 레벨 graph 파일
    if nodes_file is None:
        root_graph = data_root / "indexes" / "graph"
        root_nodes = root_graph / "graph_nodes.jsonl"
        if root_nodes.is_file():
            print(f"[경고] source_id 폴더 없음. 루트 graph_nodes.jsonl 사용")
            nodes_file = root_nodes
            edges_file = root_graph / "graph_edges.jsonl" if (root_graph / "graph_edges.jsonl").is_file() else None

    return nodes_file, edges_file


def find_wiki_files(data_root: Path, source_id: str) -> list[Path]:
    """source_id에 해당하는 Wiki 파일들을 찾는다."""
    wiki_files = []

    # 1차: data/wiki/{source_id}/ 하위
    wiki_source_dir = data_root / "wiki" / source_id
    if wiki_source_dir.is_dir():
        wiki_files.extend(wiki_source_dir.rglob("*.md"))
        wiki_files.extend(wiki_source_dir.rglob("*.json"))

    # 2차: data/wiki/multi_source/ 하위
    wiki_multi_dir = data_root / "wiki" / "multi_source"
    if wiki_multi_dir.is_dir():
        wiki_files.extend(wiki_multi_dir.rglob("*.md"))
        wiki_files.extend(wiki_multi_dir.rglob("*.json"))

    # 3차: data/wiki/projects/, data/wiki/organizations/ (레거시)
    for subdir in ["projects", "organizations", "technologies"]:
        legacy_dir = data_root / "wiki" / subdir
        if legacy_dir.is_dir():
            wiki_files.extend(legacy_dir.rglob("*.md"))
            wiki_files.extend(legacy_dir.rglob("*.json"))

    return wiki_files


# ------------------------------------------------------------------
# 3. 데이터 로드
# ------------------------------------------------------------------
def load_chunk_metadata(jsonl_files: list[Path]) -> list[dict]:
    """FAISS 청크 메타데이터 JSONL을 로드한다."""
    records = []
    if not jsonl_files:
        print("[경고] FAISS 메타데이터 JSONL 파일을 찾지 못했습니다.")
        return records

    for f in jsonl_files:
        print(f"[정보] 로드 중: {f.name}")
        with f.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"[경고] JSONL 파싱 실패: {f.name}:{line_no}")

    print(f"[정보] 청크 메타 로드 완료: {len(records)}건 / 파일 {len(jsonl_files)}개")
    return records


def load_graph_data(nodes_file: Path | None, edges_file: Path | None) -> dict | None:
    """Graph 노드/엣지를 로드한다."""
    if nodes_file is None:
        return None

    nodes = []
    edges = []

    # 노드 로드 (JSONL 형식)
    print(f"[정보] Graph 노드 로드 중: {nodes_file.name}")
    with nodes_file.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    nodes.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    # 엣지 로드 (JSONL 형식)
    if edges_file and edges_file.is_file():
        print(f"[정보] Graph 엣지 로드 중: {edges_file.name}")
        with edges_file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        edges.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    print(f"[정보] Graph 로드 완료: 노드 {len(nodes)}개, 엣지 {len(edges)}개")
    return {"nodes": nodes, "edges": edges}


def load_wiki_entries(wiki_files: list[Path]) -> list[dict]:
    """Wiki 파일 목록에서 카테고리/슬러그 정보를 추출한다."""
    entries = []

    for f in wiki_files:
        slug = f.stem
        # 카테고리 추정: 상위 폴더명
        parent = f.parent.name.lower()
        entries.append({
            "category": parent,
            "slug": slug,
            "path": str(f)
        })

    print(f"[정보] Wiki 파일 로드 완료: {len(entries)}건")
    return entries


# ------------------------------------------------------------------
# 4. (A) 메타데이터 구성 / 충족률 분석
# ------------------------------------------------------------------
def analyze_composition(records: list[dict]) -> tuple[dict, dict]:
    """청크 레코드에서 문서 단위/청크 단위 충족률을 계산한다."""
    def doc_key(r):
        return r.get("document_id") or r.get("doc_id") or r.get("source_id") or "__unknown__"

    docs = defaultdict(list)
    for r in records:
        docs[doc_key(r)].append(r)

    total_docs = len(docs)
    total_chunks = len(records)

    result = {"total_docs": total_docs, "total_chunks": total_chunks, "fields": {}}

    for field, consumers, desc in FIELD_SPEC:
        chunk_filled = sum(1 for r in records if is_filled(r.get(field)))
        doc_filled = sum(
            1 for chunks in docs.values()
            if any(is_filled(c.get(field)) for c in chunks)
        )
        result["fields"][field] = {
            "consumers": consumers,
            "desc": desc,
            "chunk_rate": chunk_filled / total_chunks if total_chunks else 0.0,
            "doc_rate": doc_filled / total_docs if total_docs else 0.0,
        }

    # 원시 번호 접두어 잔존 검사
    prefix_violations = []
    for r in records:
        for key in ("section_type", "document_group"):
            v = r.get(key)
            if isinstance(v, str) and RAW_PREFIX_RE.match(v):
                prefix_violations.append((r.get("chunk_id", "?"), key, v))
    result["prefix_violations"] = prefix_violations[:20]
    result["prefix_violation_count"] = len(prefix_violations)
    return result, docs


# ------------------------------------------------------------------
# 5. (B) 검색 기여 준비 상태 분석
# ------------------------------------------------------------------
def analyze_search_readiness(records: list[dict], comp: dict) -> dict:
    """검색 3경로별 준비 상태를 측정한다."""
    out = {}

    # 브레드크럼 주입 검사
    text_keys = ("text", "chunk_text", "content", "page_content")
    injected = 0
    checkable = 0
    for r in records:
        sp = r.get("section_path")
        if not is_filled(sp):
            continue
        text = next((r[k] for k in text_keys if isinstance(r.get(k), str)), None)
        if text is None:
            continue
        checkable += 1
        head = text[:200]
        first = sp[0] if isinstance(sp, list) and sp else str(sp)
        if ">" in head or (isinstance(first, str) and first[:10] in head):
            injected += 1
    out["breadcrumb_injection_rate"] = injected / checkable if checkable else None
    out["breadcrumb_checkable"] = checkable

    # 필터 분포
    dist = {}
    for field in ("doc_type", "year", "chunk_role"):
        c = Counter(str(r.get(field)) for r in records if is_filled(r.get(field)))
        dist[field] = dict(c.most_common(10))
    out["filter_distribution"] = dist

    # 소프트 보너스 필드 충족률
    out["bonus_fields"] = {
        f: comp["fields"][f]["doc_rate"]
        for f in ("organization_type", "business_domain", "tags")
        if f in comp["fields"]
    }
    return out


# ------------------------------------------------------------------
# 6. (C) Graph / Wiki 반영률 분석
# ------------------------------------------------------------------
def collect_meta_entities(records: list[dict]) -> dict[str, set]:
    """메타데이터에서 필드별 고유 엔티티 값 집합을 만든다."""
    entities = defaultdict(set)
    for r in records:
        for field in set(list(GRAPH_NODE_TYPE_MAP) + list(WIKI_CATEGORY_MAP)):
            for val in iter_values(r.get(field)):
                entities[field].add(norm_key(val))
    return entities


def analyze_graph_coverage(graph: dict | None, entities: dict[str, set]) -> dict:
    """메타 엔티티 값이 Graph 노드로 몇 % 반영됐는지 계산한다."""
    if graph is None:
        return {"available": False}

    nodes_by_type = defaultdict(set)
    for node in graph.get("nodes", []):
        ntype = str(node.get("type") or node.get("label") or node.get("node_type") or "").lower()
        name = node.get("name") or node.get("id") or node.get("title") or node.get("node_id") or ""
        if name:
            nodes_by_type[ntype].add(norm_key(name))

    coverage = {}
    for field, type_candidates in GRAPH_NODE_TYPE_MAP.items():
        meta_vals = entities.get(field, set())
        if not meta_vals:
            coverage[field] = {"meta_count": 0, "covered": 0, "rate": None}
            continue
        node_vals = set()
        for t in type_candidates:
            node_vals |= nodes_by_type.get(t, set())
        covered = len(meta_vals & node_vals)
        coverage[field] = {
            "meta_count": len(meta_vals),
            "covered": covered,
            "rate": covered / len(meta_vals) if meta_vals else 0,
            "graph_node_count": len(node_vals),
        }
    return {
        "available": True,
        "total_nodes": len(graph.get("nodes", [])),
        "total_edges": len(graph.get("edges", [])),
        "coverage": coverage,
    }


def analyze_wiki_coverage(wiki_entries: list[dict], entities: dict[str, set]) -> dict:
    """메타 엔티티 값이 Wiki 페이지로 몇 % 반영됐는지 계산한다."""
    if not wiki_entries:
        return {"available": False}

    slugs_by_cat = defaultdict(set)
    for e in wiki_entries:
        slugs_by_cat[e["category"]].add(norm_key(e["slug"]))
        slugs_by_cat["__all__"].add(norm_key(e["slug"]))

    coverage = {}
    for field, cats in WIKI_CATEGORY_MAP.items():
        meta_vals = entities.get(field, set())
        if not meta_vals:
            coverage[field] = {"meta_count": 0, "covered": 0, "rate": None}
            continue
        wiki_vals = set()
        for c in cats:
            wiki_vals |= slugs_by_cat.get(c, set())
        if not wiki_vals:
            wiki_vals = slugs_by_cat["__all__"]
        covered = len(meta_vals & wiki_vals)
        coverage[field] = {
            "meta_count": len(meta_vals),
            "covered": covered,
            "rate": covered / len(meta_vals) if meta_vals else 0,
            "wiki_page_count": len(wiki_vals),
        }
    return {"available": True, "total_pages": len(wiki_entries), "coverage": coverage}


# ------------------------------------------------------------------
# 7. 리포트 출력
# ------------------------------------------------------------------
def pct(v) -> str:
    """비율 → '87.5%' 형식. None이면 '—'."""
    return "—" if v is None else f"{v * 100:5.1f}%"


def print_report(source_id: str, comp: dict, search: dict,
                 graph_cov: dict, wiki_cov: dict) -> dict:
    """콘솔 리포트를 출력하고, 동일 내용을 dict(JSON 저장용)로 반환한다."""
    print()
    print("=" * 68)
    print(f" weeslee-rag 메타데이터 기여도 진단  /  source_id: {source_id}")
    print("=" * 68)

    # --- (A) 구성/충족률 ---
    print(f"\n[A] 메타데이터 구성 및 충족률  (문서 {comp['total_docs']}건 / 청크 {comp['total_chunks']}건)")
    print(f"  {'필드':<18}{'문서충족':>8}{'청크충족':>8}  소비처")
    for field, info in comp["fields"].items():
        print(f"  {field:<18}{pct(info['doc_rate']):>8}{pct(info['chunk_rate']):>8}  "
              f"{','.join(info['consumers'])} — {info['desc']}")

    if comp["prefix_violation_count"]:
        print(f"\n  ⚠ 원시 번호 접두어 잔존: {comp['prefix_violation_count']}건 "
              f"(section_type/document_group) → 하드 필터 0건 사고 위험!")
        for cid, key, val in comp["prefix_violations"][:5]:
            print(f"     - chunk={cid} {key}='{val}'")
    else:
        print("\n  ✓ 원시 번호 접두어 잔존 없음")

    # --- (B) 검색 기여 ---
    print("\n[B] 검색 기여 준비 상태")
    print(f"  임베딩 주입(브레드크럼 prefix): {pct(search['breadcrumb_injection_rate'])} "
          f"(검사 가능 청크 {search['breadcrumb_checkable']}건)")
    print("  하드 필터 분포:")
    for f, dist in search["filter_distribution"].items():
        print(f"    - {f}: {dist if dist else '값 없음 → 필터 무의미'}")
    print("  소프트 보너스 필드 충족률(문서 기준):")
    for f, rate in search["bonus_fields"].items():
        print(f"    - {f}: {pct(rate)}")

    # --- (C) Graph 반영률 ---
    print("\n[C-1] Graph 반영률 (메타 엔티티 → Graph 노드)")
    if graph_cov.get("available"):
        print(f"  Graph 전체: 노드 {graph_cov['total_nodes']} / 엣지 {graph_cov['total_edges']}")
        for field, c in graph_cov["coverage"].items():
            print(f"  {field:<14} 메타 {c['meta_count']:>4}개 → 노드 반영 "
                  f"{c['covered']:>4}개 ({pct(c['rate'])})")
    else:
        print("  Graph 파일을 찾지 못함 → 아직 미생성이거나 경로가 다름")

    # --- (C) Wiki 반영률 ---
    print("\n[C-2] Wiki 반영률 (메타 엔티티 → Wiki 페이지)")
    if wiki_cov.get("available"):
        print(f"  Wiki 전체 페이지: {wiki_cov['total_pages']}건")
        for field, c in wiki_cov["coverage"].items():
            print(f"  {field:<14} 메타 {c['meta_count']:>4}개 → 페이지 반영 "
                  f"{c['covered']:>4}개 ({pct(c['rate'])})")
    else:
        print("  Wiki 파일을 찾지 못함 → 아직 미생성이거나 경로가 다름")

    # --- GO/NO-GO 판정 ---
    print("\n[판정] Graph/Wiki 생성 가능성 (핵심 엔티티 필드 문서 충족률 기준)")
    verdict = "GO"
    for f in CRITICAL_ENTITY_FIELDS:
        rate = comp["fields"][f]["doc_rate"]
        mark = "✓" if rate >= GO_THRESHOLD else "✗"
        if rate < GO_THRESHOLD:
            verdict = "NO-GO"
        print(f"  {mark} {f}: {pct(rate)} (임계값 {pct(GO_THRESHOLD)})")
    print(f"  → 종합: {verdict}"
          + ("" if verdict == "GO"
             else " — Metadata Build 단계의 엔티티 추출부터 보강 필요"))
    print("=" * 68)

    return {
        "source_id": source_id,
        "composition": {k: v for k, v in comp.items() if k != "prefix_violations"},
        "search_readiness": search,
        "graph_coverage": graph_cov,
        "wiki_coverage": wiki_cov,
        "verdict": verdict,
    }


# ------------------------------------------------------------------
# 8. 메인
# ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="weeslee-rag 메타데이터 구성·검색 기여·Graph/Wiki 반영률 진단")
    parser.add_argument("--data-root", required=True, type=Path,
                        help="데이터 루트 (예: /data/weeslee/weeslee-rag/data)")
    parser.add_argument("--source-id", required=True,
                        help="분석할 source_id (예: src_20260710_111246_d478a8)")
    parser.add_argument("--report-out", default=None, type=Path,
                        help="JSON 리포트 저장 경로 (선택)")
    args = parser.parse_args()

    if not args.data_root.is_dir():
        sys.exit(f"[오류] data-root가 존재하지 않습니다: {args.data_root}")

    source_id = args.source_id
    print(f"[정보] source_id: {source_id}")
    print(f"[정보] data-root: {args.data_root}")
    print()

    # 1) FAISS 메타데이터 로드
    faiss_files = find_faiss_metadata(args.data_root, source_id)
    records = load_chunk_metadata(faiss_files)

    if not records:
        sys.exit("[오류] 청크 메타데이터를 찾지 못했습니다. source_id를 확인하세요.")

    # 2) Graph 데이터 로드
    nodes_file, edges_file = find_graph_files(args.data_root, source_id)
    graph_data = load_graph_data(nodes_file, edges_file)

    # 3) Wiki 파일 로드
    wiki_files = find_wiki_files(args.data_root, source_id)
    wiki_entries = load_wiki_entries(wiki_files)

    # 4) (A) 구성/충족률
    comp, _docs = analyze_composition(records)

    # 5) (B) 검색 기여 준비 상태
    search = analyze_search_readiness(records, comp)

    # 6) (C) Graph/Wiki 교차 검증
    entities = collect_meta_entities(records)
    graph_cov = analyze_graph_coverage(graph_data, entities)
    wiki_cov = analyze_wiki_coverage(wiki_entries, entities)

    # 7) 리포트 출력 + 저장
    report = print_report(source_id, comp, search, graph_cov, wiki_cov)
    if args.report_out:
        args.report_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[정보] JSON 리포트 저장: {args.report_out}")


if __name__ == "__main__":
    main()
