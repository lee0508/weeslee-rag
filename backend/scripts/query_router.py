# 4-layer RAG 검색 시스템의 Query Router - 쿼리 유형 분류 및 검색 계층 라우팅
"""
Query Router for weeslee-rag 4-layer search system.

4-layer search architecture:
  1차: FAISS Index (chunk search) - 벡터 유사도 기반 청크 검색
  2차: Ontology (concept expansion) - 용어 확장 및 동의어 매핑
  3차: GraphRAG (relationship traversal) - 그래프 관계 기반 문서 탐색
  4차: LLM Wiki (knowledge summary) - 위키 지식 기반 요약 생성

Query types:
  - factual: 사실 기반 질문 (1차 FAISS 우선)
  - conceptual: 개념/정의 질문 (2차 Ontology 우선)
  - relational: 관계/비교 질문 (3차 GraphRAG 우선)
  - summary: 요약/종합 질문 (4차 LLM Wiki 우선)

Usage:
    router = QueryRouter()
    result = router.route("한국수자원공사 ISP 사업에서 사용한 기술은?")
    # result.query_type = 'relational'
    # result.layers = [3, 1, 2]  # GraphRAG -> FAISS -> Ontology
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class QueryType(Enum):
    """Query classification types."""
    FACTUAL = 'factual'        # 1차 FAISS 우선
    CONCEPTUAL = 'conceptual'  # 2차 Ontology 우선
    RELATIONAL = 'relational'  # 3차 GraphRAG 우선
    SUMMARY = 'summary'        # 4차 LLM Wiki 우선
    UNKNOWN = 'unknown'        # 기본값


class SearchLayer(Enum):
    """Search layer identifiers."""
    FAISS = 1       # Vector similarity search
    ONTOLOGY = 2    # Concept expansion
    GRAPHRAG = 3    # Graph traversal
    LLM_WIKI = 4    # Knowledge summary


@dataclass
class RouteResult:
    """Query routing result."""
    query: str
    query_type: QueryType
    layers: list[SearchLayer]  # Ordered list of layers to use
    confidence: float
    extracted_entities: list[str] = field(default_factory=list)
    expanded_terms: list[str] = field(default_factory=list)
    filters: dict = field(default_factory=dict)  # category, date_range, organization, etc.
    reasoning: str = ""


class QueryRouter:
    """
    Routes queries to appropriate search layers based on query type.

    Layer routing strategy:
    - factual: FAISS(1) -> Ontology(2) -> GraphRAG(3)
    - conceptual: Ontology(2) -> FAISS(1) -> LLM_Wiki(4)
    - relational: GraphRAG(3) -> FAISS(1) -> Ontology(2)
    - summary: LLM_Wiki(4) -> GraphRAG(3) -> FAISS(1)
    """

    # Query type patterns (Korean)
    PATTERNS = {
        QueryType.FACTUAL: [
            r'무엇인가요?',
            r'어떤\s*것',
            r'무슨',
            r'뭔가요?',
            r'언제',
            r'어디',
            r'누가',
            r'몇\s*(개|명|건)',
            r'정의',
            r'의미',
            r'설명',
        ],
        QueryType.CONCEPTUAL: [
            r'개념',
            r'정의가?\s*뭐',
            r'이?란\s*무엇',
            r'의미는?',
            r'특징',
            r'차이점?',
            r'종류',
            r'유형',
            r'분류',
            r'방법론',
            r'기술\s*(?:이란|이?라는|은\s*무엇)',
        ],
        QueryType.RELATIONAL: [
            r'관계',
            r'연관',
            r'연결',
            r'관련\s*(문서|프로젝트|사업)',
            r'비교',
            r'유사',
            r'같은\s*(유형|종류)',
            r'에서\s*사용',
            r'적용\s*사례',
            r'참고\s*할\s*(수\s*있는|만한)',
            r'레퍼런스',
            r'기반으로',
            r'참조',
        ],
        QueryType.SUMMARY: [
            r'요약',
            r'정리',
            r'종합',
            r'전체\s*내용',
            r'핵심\s*내용',
            r'주요\s*내용',
            r'개요',
            r'브리핑',
            r'한\s*눈에',
            r'전반적',
        ],
    }

    # Entity extraction patterns
    ENTITY_PATTERNS = {
        'organization': [
            r'([가-힣]+(?:공사|공단|원|부|처|청|위원회|연구원|진흥원|센터|대학교?|병원))',
            r'([A-Z]{2,}(?:\s+[A-Z][a-z]+)*)',  # Acronyms like IBM, LG CNS
        ],
        'project_keyword': [
            r'(ISP|ISMP|ODA|BPR|ITA|EA|PMO|감리)',
            r'(정보화\s*(?:전략|사업|계획))',
            r'(시스템\s*(?:구축|개발|운영))',
        ],
        'technology': [
            r'(AI|ML|DL|빅데이터|클라우드|블록체인|IoT|RPA)',
            r'(Java|Python|React|Vue|Spring|Django)',
            r'(AWS|Azure|GCP|Oracle|SAP)',
        ],
        'category': [
            r'(RFP|제안서|착수보고서?|최종보고서?|발표자료)',
            r'(제안\s*요청서?|착수\s*보고|최종\s*보고)',
        ],
    }

    # Default layer order by query type
    LAYER_ORDER = {
        QueryType.FACTUAL: [SearchLayer.FAISS, SearchLayer.ONTOLOGY, SearchLayer.GRAPHRAG],
        QueryType.CONCEPTUAL: [SearchLayer.ONTOLOGY, SearchLayer.FAISS, SearchLayer.LLM_WIKI],
        QueryType.RELATIONAL: [SearchLayer.GRAPHRAG, SearchLayer.FAISS, SearchLayer.ONTOLOGY],
        QueryType.SUMMARY: [SearchLayer.LLM_WIKI, SearchLayer.GRAPHRAG, SearchLayer.FAISS],
        QueryType.UNKNOWN: [SearchLayer.FAISS, SearchLayer.ONTOLOGY, SearchLayer.GRAPHRAG],
    }

    def __init__(self, terms_path: Optional[str | Path] = None):
        """
        Initialize query router.

        Args:
            terms_path: Path to ontology terms.jsonl for entity matching
        """
        self.terms: dict[str, dict] = {}  # term_id -> term data
        self.term_index: dict[str, str] = {}  # label/synonym -> term_id

        if terms_path:
            self._load_terms(terms_path)

    def _load_terms(self, terms_path: str | Path) -> None:
        """Load ontology terms for entity matching."""
        with open(terms_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                term = json.loads(line)
                term_id = term['term_id']
                self.terms[term_id] = term

                # Index by label
                label = term.get('label', '')
                if label:
                    self.term_index[label.lower()] = term_id

                # Index by synonyms
                for synonym in term.get('synonyms', []):
                    self.term_index[synonym.lower()] = term_id

    def classify_query(self, query: str) -> tuple[QueryType, float, str]:
        """
        Classify query into one of the query types.

        Returns:
            (QueryType, confidence, reasoning)
        """
        query_lower = query.lower()
        scores = {qt: 0.0 for qt in QueryType}

        # Pattern matching
        for query_type, patterns in self.PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    scores[query_type] += 1.0

        # Find best match
        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]

        if best_score == 0:
            return QueryType.UNKNOWN, 0.3, "No pattern matched, defaulting to factual search"

        # Normalize confidence
        total = sum(scores.values())
        confidence = best_score / total if total > 0 else 0.3

        reasoning = f"Matched patterns for {best_type.value} query type"
        return best_type, min(confidence, 0.95), reasoning

    def extract_entities(self, query: str) -> dict[str, list[str]]:
        """
        Extract named entities from query.

        Returns:
            Dict of entity_type -> [extracted values]
        """
        entities = {
            'organizations': [],
            'projects': [],
            'technologies': [],
            'categories': [],
            'terms': [],  # Matched ontology terms
        }

        # Pattern-based extraction
        for entity_type, patterns in self.ENTITY_PATTERNS.items():
            for pattern in patterns:
                matches = re.findall(pattern, query, re.IGNORECASE)
                if entity_type == 'organization':
                    entities['organizations'].extend(matches)
                elif entity_type == 'project_keyword':
                    entities['projects'].extend(matches)
                elif entity_type == 'technology':
                    entities['technologies'].extend(matches)
                elif entity_type == 'category':
                    entities['categories'].extend(matches)

        # Match against ontology terms
        query_lower = query.lower()
        for term_label, term_id in self.term_index.items():
            if term_label in query_lower:
                term = self.terms.get(term_id, {})
                entities['terms'].append({
                    'term_id': term_id,
                    'label': term.get('label', term_label),
                    'type': term.get('type', 'unknown')
                })

        # Deduplicate
        for key in ['organizations', 'projects', 'technologies', 'categories']:
            entities[key] = list(set(entities[key]))

        return entities

    def expand_terms(self, entities: dict) -> list[str]:
        """
        Expand extracted entities using ontology synonyms.

        Returns:
            List of expanded terms for search
        """
        expanded = []

        # Add matched terms and their synonyms
        for term_info in entities.get('terms', []):
            term_id = term_info['term_id']
            term = self.terms.get(term_id, {})

            expanded.append(term.get('label', ''))
            expanded.extend(term.get('synonyms', []))

        # Add raw entities
        for key in ['organizations', 'projects', 'technologies', 'categories']:
            expanded.extend(entities.get(key, []))

        return list(set(e for e in expanded if e))

    def extract_filters(self, query: str, entities: dict) -> dict:
        """
        Extract search filters from query.

        Returns:
            Dict of filter_name -> filter_value
        """
        filters = {}

        # Category filter
        category_map = {
            'rfp': 'rfp',
            '제안요청': 'rfp',
            '제안서': 'proposal',
            '착수보고': 'kickoff',
            '착수': 'kickoff',
            '최종보고': 'final_report',
            '발표': 'presentation',
        }

        for keyword, category in category_map.items():
            if keyword in query.lower():
                filters['category'] = category
                break

        # Organization filter
        if entities.get('organizations'):
            filters['organization'] = entities['organizations'][0]

        # Date range (basic extraction)
        year_match = re.search(r'(20\d{2})\s*년?', query)
        if year_match:
            filters['year'] = int(year_match.group(1))

        return filters

    def route(self, query: str) -> RouteResult:
        """
        Route a query to appropriate search layers.

        Args:
            query: User's search query

        Returns:
            RouteResult with routing information
        """
        # 1. Classify query type
        query_type, confidence, reasoning = self.classify_query(query)

        # 2. Extract entities
        entities = self.extract_entities(query)

        # 3. Expand terms using ontology
        expanded_terms = self.expand_terms(entities)

        # 4. Extract filters
        filters = self.extract_filters(query, entities)

        # 5. Determine layer order
        layers = self.LAYER_ORDER[query_type].copy()

        # Adjust layers based on entities
        if entities.get('terms') and SearchLayer.ONTOLOGY not in layers[:2]:
            # Boost ontology layer if terms were matched
            layers.remove(SearchLayer.ONTOLOGY)
            layers.insert(1, SearchLayer.ONTOLOGY)

        # 6. Build extracted entities list (flat)
        extracted = []
        for term_info in entities.get('terms', []):
            extracted.append(term_info['label'])
        for key in ['organizations', 'projects', 'technologies']:
            extracted.extend(entities.get(key, []))

        return RouteResult(
            query=query,
            query_type=query_type,
            layers=layers,
            confidence=confidence,
            extracted_entities=list(set(extracted)),
            expanded_terms=expanded_terms,
            filters=filters,
            reasoning=reasoning
        )

    def to_dict(self, result: RouteResult) -> dict:
        """Convert RouteResult to JSON-serializable dict."""
        return {
            'query': result.query,
            'query_type': result.query_type.value,
            'layers': [layer.value for layer in result.layers],
            'layer_names': [layer.name for layer in result.layers],
            'confidence': result.confidence,
            'extracted_entities': result.extracted_entities,
            'expanded_terms': result.expanded_terms,
            'filters': result.filters,
            'reasoning': result.reasoning
        }


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    from pathlib import Path

    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    ONTOLOGY_DIR = PROJECT_ROOT / 'data' / 'ontology'
    terms_path = ONTOLOGY_DIR / 'terms.jsonl'

    # Initialize router
    print("[INFO] Initializing Query Router...")
    router = QueryRouter(terms_path=terms_path if terms_path.exists() else None)
    print(f"[INFO] Loaded {len(router.terms)} ontology terms")

    # Test queries
    test_queries = [
        # Factual queries
        "한국수자원공사 ISP 사업은 언제 진행되었나요?",
        "정보화전략계획 수립 프로젝트에서 사용한 방법론은 무엇인가요?",

        # Conceptual queries
        "EA(Enterprise Architecture)의 정의와 특징은 무엇인가요?",
        "ISP와 ISMP의 차이점을 설명해주세요",

        # Relational queries
        "한국수자원공사 ISP와 유사한 프로젝트를 찾아주세요",
        "AI 기술을 적용한 사례가 있는 프로젝트는?",
        "농정원 프로젝트에서 참고할 만한 제안서가 있나요?",

        # Summary queries
        "디지털 전환 관련 프로젝트들의 핵심 내용을 요약해주세요",
        "2023년 진행된 사업들을 전반적으로 정리해주세요",

        # Mixed/Unknown
        "AGRIX 시스템",
        "클라우드 마이그레이션",
    ]

    print("\n" + "="*80)
    print("Query Routing Test Results")
    print("="*80)

    for query in test_queries:
        result = router.route(query)
        result_dict = router.to_dict(result)

        print(f"\n[Query] {query}")
        print(f"  Type: {result_dict['query_type']} (confidence: {result_dict['confidence']:.2f})")
        print(f"  Layers: {' -> '.join(result_dict['layer_names'])}")
        if result_dict['extracted_entities']:
            print(f"  Entities: {result_dict['extracted_entities'][:5]}")
        if result_dict['filters']:
            print(f"  Filters: {result_dict['filters']}")
        if result_dict['expanded_terms']:
            print(f"  Expanded: {result_dict['expanded_terms'][:5]}")

    print("\n" + "="*80)
    print("[DONE] Query Router test completed.")
