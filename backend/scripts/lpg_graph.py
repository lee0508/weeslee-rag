# LPG(Labeled Property Graph) 그래프 클래스 - 노드/엣지 JSONL을 메모리에 로드하고 탐색/쿼리 기능 제공
"""
LPG Graph Class for weeslee-rag GraphRAG system.

4-layer search system support:
  1차: FAISS Index (chunk search)
  2차: Ontology (concept expansion)
  3차: GraphRAG (relationship traversal) <- This module
  4차: LLM Wiki (knowledge summary)

Usage:
    graph = LPGGraph()
    graph.load_from_jsonl(nodes_path, edges_path)

    # Get neighbors
    neighbors = graph.get_neighbors("doc:DOC-20260427-000001")

    # Find path
    path = graph.find_path("doc:DOC-20260427-000001", "proj:한국수자원공사-2023")

    # Get subgraph for visualization
    subgraph = graph.get_subgraph(["doc:DOC-20260427-000001"], depth=2)
"""

import json
from pathlib import Path
from typing import Optional
from collections import defaultdict
from datetime import datetime


class LPGGraph:
    """Labeled Property Graph implementation for GraphRAG."""

    def __init__(self):
        self.nodes: dict[str, dict] = {}  # node_id -> node data
        self.edges: dict[str, dict] = {}  # edge_id -> edge data

        # Adjacency lists for fast traversal
        self._outgoing: dict[str, list[str]] = defaultdict(list)  # node_id -> [edge_ids]
        self._incoming: dict[str, list[str]] = defaultdict(list)  # node_id -> [edge_ids]

        # Type indexes for filtering
        self._nodes_by_type: dict[str, set[str]] = defaultdict(set)  # node_type -> {node_ids}
        self._edges_by_type: dict[str, set[str]] = defaultdict(set)  # edge_type -> {edge_ids}

        self.schema: Optional[dict] = None
        self.loaded_at: Optional[str] = None

    def load_schema(self, schema_path: str | Path) -> None:
        """Load LPG schema for type validation."""
        with open(schema_path, 'r', encoding='utf-8') as f:
            self.schema = json.load(f)

    def load_from_jsonl(self, nodes_path: str | Path, edges_path: str | Path) -> dict:
        """
        Load graph from JSONL files.

        Returns:
            dict with statistics about loaded data
        """
        nodes_path = Path(nodes_path)
        edges_path = Path(edges_path)

        # Clear existing data
        self.nodes.clear()
        self.edges.clear()
        self._outgoing.clear()
        self._incoming.clear()
        self._nodes_by_type.clear()
        self._edges_by_type.clear()

        # Load nodes
        node_count = 0
        with open(nodes_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                node = json.loads(line)
                node_id = node['node_id']
                self.nodes[node_id] = node
                self._nodes_by_type[node['node_type']].add(node_id)
                node_count += 1

        # Load edges
        edge_count = 0
        with open(edges_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                edge = json.loads(line)
                edge_id = edge['edge_id']
                self.edges[edge_id] = edge

                source = edge['source_node']
                target = edge['target_node']

                self._outgoing[source].append(edge_id)
                self._incoming[target].append(edge_id)
                self._edges_by_type[edge['edge_type']].add(edge_id)
                edge_count += 1

        self.loaded_at = datetime.now().isoformat()

        return {
            'nodes': node_count,
            'edges': edge_count,
            'node_types': {k: len(v) for k, v in self._nodes_by_type.items()},
            'edge_types': {k: len(v) for k, v in self._edges_by_type.items()},
            'loaded_at': self.loaded_at
        }

    # ─────────────────────────────────────────────────────────────────
    # Node Operations
    # ─────────────────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[dict]:
        """Get node by ID."""
        return self.nodes.get(node_id)

    def get_nodes_by_type(self, node_type: str) -> list[dict]:
        """Get all nodes of a specific type."""
        return [self.nodes[nid] for nid in self._nodes_by_type.get(node_type, set())]

    def search_nodes(self, query: str, node_types: Optional[list[str]] = None, limit: int = 20) -> list[dict]:
        """
        Search nodes by label/properties containing query string.

        Args:
            query: Search string (case-insensitive)
            node_types: Filter by node types (None = all types)
            limit: Maximum results to return
        """
        query_lower = query.lower()
        results = []

        candidates = self.nodes.values()
        if node_types:
            candidate_ids = set()
            for nt in node_types:
                candidate_ids.update(self._nodes_by_type.get(nt, set()))
            candidates = [self.nodes[nid] for nid in candidate_ids]

        for node in candidates:
            # Search in labels
            labels = node.get('labels', [])
            if any(query_lower in label.lower() for label in labels):
                results.append(node)
                continue

            # Search in properties
            props = node.get('properties', {})
            prop_values = ' '.join(str(v) for v in props.values() if v)
            if query_lower in prop_values.lower():
                results.append(node)

        return results[:limit]

    # ─────────────────────────────────────────────────────────────────
    # Edge Operations
    # ─────────────────────────────────────────────────────────────────

    def get_edge(self, edge_id: str) -> Optional[dict]:
        """Get edge by ID."""
        return self.edges.get(edge_id)

    def get_edges_by_type(self, edge_type: str) -> list[dict]:
        """Get all edges of a specific type."""
        return [self.edges[eid] for eid in self._edges_by_type.get(edge_type, set())]

    def get_edges_between(self, source_id: str, target_id: str) -> list[dict]:
        """Get all edges between two nodes."""
        outgoing = self._outgoing.get(source_id, [])
        return [
            self.edges[eid] for eid in outgoing
            if self.edges[eid]['target_node'] == target_id
        ]

    # ─────────────────────────────────────────────────────────────────
    # Graph Traversal
    # ─────────────────────────────────────────────────────────────────

    def get_neighbors(
        self,
        node_id: str,
        direction: str = 'both',  # 'outgoing', 'incoming', 'both'
        edge_types: Optional[list[str]] = None,
        node_types: Optional[list[str]] = None
    ) -> list[dict]:
        """
        Get neighboring nodes with edge information.

        Returns:
            List of dicts with 'node', 'edge', 'direction' keys
        """
        neighbors = []

        # Outgoing edges (node -> neighbor)
        if direction in ('outgoing', 'both'):
            for edge_id in self._outgoing.get(node_id, []):
                edge = self.edges[edge_id]
                if edge_types and edge['edge_type'] not in edge_types:
                    continue
                target_node = self.nodes.get(edge['target_node'])
                if not target_node:
                    continue
                if node_types and target_node['node_type'] not in node_types:
                    continue
                neighbors.append({
                    'node': target_node,
                    'edge': edge,
                    'direction': 'outgoing'
                })

        # Incoming edges (neighbor -> node)
        if direction in ('incoming', 'both'):
            for edge_id in self._incoming.get(node_id, []):
                edge = self.edges[edge_id]
                if edge_types and edge['edge_type'] not in edge_types:
                    continue
                source_node = self.nodes.get(edge['source_node'])
                if not source_node:
                    continue
                if node_types and source_node['node_type'] not in node_types:
                    continue
                neighbors.append({
                    'node': source_node,
                    'edge': edge,
                    'direction': 'incoming'
                })

        return neighbors

    def find_path(
        self,
        start_id: str,
        end_id: str,
        max_depth: int = 5,
        edge_types: Optional[list[str]] = None
    ) -> Optional[list[dict]]:
        """
        Find shortest path between two nodes using BFS.

        Returns:
            List of {'node': node, 'edge': edge} from start to end, or None if no path
        """
        if start_id == end_id:
            return [{'node': self.nodes.get(start_id), 'edge': None}]

        if start_id not in self.nodes or end_id not in self.nodes:
            return None

        # BFS
        from collections import deque

        # queue entries: (current_node_id, path_so_far)
        queue = deque([(start_id, [{'node': self.nodes[start_id], 'edge': None}])])
        visited = {start_id}

        while queue:
            current_id, path = queue.popleft()

            if len(path) > max_depth:
                continue

            # Check all outgoing edges
            for edge_id in self._outgoing.get(current_id, []):
                edge = self.edges[edge_id]
                if edge_types and edge['edge_type'] not in edge_types:
                    continue

                neighbor_id = edge['target_node']
                if neighbor_id in visited:
                    continue

                neighbor_node = self.nodes.get(neighbor_id)
                if not neighbor_node:
                    continue

                new_path = path + [{'node': neighbor_node, 'edge': edge}]

                if neighbor_id == end_id:
                    return new_path

                visited.add(neighbor_id)
                queue.append((neighbor_id, new_path))

            # Also check incoming edges (undirected traversal)
            for edge_id in self._incoming.get(current_id, []):
                edge = self.edges[edge_id]
                if edge_types and edge['edge_type'] not in edge_types:
                    continue

                neighbor_id = edge['source_node']
                if neighbor_id in visited:
                    continue

                neighbor_node = self.nodes.get(neighbor_id)
                if not neighbor_node:
                    continue

                new_path = path + [{'node': neighbor_node, 'edge': edge}]

                if neighbor_id == end_id:
                    return new_path

                visited.add(neighbor_id)
                queue.append((neighbor_id, new_path))

        return None

    def get_subgraph(
        self,
        seed_node_ids: list[str],
        depth: int = 2,
        edge_types: Optional[list[str]] = None,
        max_nodes: int = 100
    ) -> dict:
        """
        Extract a subgraph around seed nodes for visualization.

        Args:
            seed_node_ids: Starting node IDs
            depth: How many hops to expand
            edge_types: Filter edges (None = all)
            max_nodes: Maximum nodes in subgraph

        Returns:
            dict with 'nodes' and 'edges' lists ready for visualization
        """
        collected_nodes: dict[str, dict] = {}
        collected_edges: dict[str, dict] = {}

        current_frontier = set()
        for nid in seed_node_ids:
            if nid in self.nodes:
                collected_nodes[nid] = self.nodes[nid]
                current_frontier.add(nid)

        for _ in range(depth):
            if len(collected_nodes) >= max_nodes:
                break

            next_frontier = set()

            for node_id in current_frontier:
                neighbors = self.get_neighbors(node_id, edge_types=edge_types)

                for neighbor_info in neighbors:
                    neighbor_node = neighbor_info['node']
                    edge = neighbor_info['edge']

                    if len(collected_nodes) >= max_nodes:
                        break

                    neighbor_id = neighbor_node['node_id']
                    if neighbor_id not in collected_nodes:
                        collected_nodes[neighbor_id] = neighbor_node
                        next_frontier.add(neighbor_id)

                    edge_id = edge['edge_id']
                    if edge_id not in collected_edges:
                        collected_edges[edge_id] = edge

            current_frontier = next_frontier

        return {
            'nodes': list(collected_nodes.values()),
            'edges': list(collected_edges.values()),
            'seed_node_ids': seed_node_ids,
            'depth': depth,
            'node_count': len(collected_nodes),
            'edge_count': len(collected_edges)
        }

    # ─────────────────────────────────────────────────────────────────
    # GraphRAG Query Support
    # ─────────────────────────────────────────────────────────────────

    def expand_by_ontology(self, term_ids: list[str], include_parents: bool = True) -> list[str]:
        """
        Expand term nodes to include related terms via ontology hierarchy.

        Used for 2nd layer (Ontology expansion) before 3rd layer traversal.
        """
        expanded = set(term_ids)

        for term_id in term_ids:
            if term_id not in self.nodes:
                continue

            # Get PARENT_TECH edges (child -> parent)
            if include_parents:
                for edge_id in self._outgoing.get(term_id, []):
                    edge = self.edges[edge_id]
                    if edge['edge_type'] == 'PARENT_TECH':
                        expanded.add(edge['target_node'])

            # Get child terms (other nodes pointing to this via PARENT_TECH)
            for edge_id in self._incoming.get(term_id, []):
                edge = self.edges[edge_id]
                if edge['edge_type'] == 'PARENT_TECH':
                    expanded.add(edge['source_node'])

        return list(expanded)

    def find_related_documents(
        self,
        doc_id: str,
        relation_types: Optional[list[str]] = None,
        max_results: int = 10
    ) -> list[dict]:
        """
        Find documents related to a given document.

        Args:
            doc_id: Source document ID
            relation_types: Filter by relation types (SIMILAR_TO, RELATED_SEQUENCE, BELONGS_TO)
            max_results: Maximum documents to return

        Returns:
            List of {'document': node, 'relation': edge, 'score': float}
        """
        if relation_types is None:
            relation_types = ['SIMILAR_TO', 'RELATED_SEQUENCE']

        results = []

        # Direct document relations
        neighbors = self.get_neighbors(
            doc_id,
            edge_types=relation_types,
            node_types=['Document']
        )

        for neighbor_info in neighbors:
            score = 1.0
            edge_props = neighbor_info['edge'].get('properties', {})
            if 'weight' in edge_props:
                score = edge_props['weight']
            elif 'similarity_score' in edge_props:
                score = edge_props['similarity_score']

            results.append({
                'document': neighbor_info['node'],
                'relation': neighbor_info['edge'],
                'score': score
            })

        # Also find documents in the same project
        project_neighbors = self.get_neighbors(
            doc_id,
            direction='incoming',
            edge_types=['HAS_DOCUMENT']
        )

        for pn in project_neighbors:
            project_node = pn['node']
            project_docs = self.get_neighbors(
                project_node['node_id'],
                direction='outgoing',
                edge_types=['HAS_DOCUMENT'],
                node_types=['Document']
            )

            for pd in project_docs:
                if pd['node']['node_id'] != doc_id:
                    # Avoid duplicates
                    if not any(r['document']['node_id'] == pd['node']['node_id'] for r in results):
                        results.append({
                            'document': pd['node'],
                            'relation': pd['edge'],
                            'score': 0.5  # Lower score for same-project docs
                        })

        # Sort by score descending
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:max_results]

    def get_document_context(self, doc_id: str) -> dict:
        """
        Get full context for a document (project, category, entities).

        Used for enriching RAG results with graph context.
        """
        context = {
            'document': self.nodes.get(doc_id),
            'project': None,
            'category': None,
            'source': None,
            'organizations': [],
            'technologies': [],
            'methodologies': [],
            'domains': [],
            'related_documents': []
        }

        if not context['document']:
            return context

        neighbors = self.get_neighbors(doc_id)

        for n in neighbors:
            node = n['node']
            edge = n['edge']
            node_type = node['node_type']
            edge_type = edge['edge_type']
            direction = n['direction']

            if node_type == 'Project' and direction == 'incoming':
                context['project'] = node
            elif node_type == 'Category':
                context['category'] = node
            elif node_type == 'Source':
                context['source'] = node
            elif node_type == 'Organization':
                context['organizations'].append(node)
            elif node_type == 'Technology':
                context['technologies'].append(node)
            elif node_type == 'Methodology':
                context['methodologies'].append(node)
            elif node_type == 'Domain':
                context['domains'].append(node)
            elif node_type == 'Document' and edge_type in ('SIMILAR_TO', 'RELATED_SEQUENCE'):
                context['related_documents'].append({
                    'document': node,
                    'relation': edge_type
                })

        return context

    # ─────────────────────────────────────────────────────────────────
    # Statistics and Export
    # ─────────────────────────────────────────────────────────────────

    def get_statistics(self) -> dict:
        """Get graph statistics."""
        return {
            'total_nodes': len(self.nodes),
            'total_edges': len(self.edges),
            'node_types': {k: len(v) for k, v in self._nodes_by_type.items()},
            'edge_types': {k: len(v) for k, v in self._edges_by_type.items()},
            'loaded_at': self.loaded_at
        }

    def to_vis_format(self, subgraph: Optional[dict] = None) -> dict:
        """
        Convert graph/subgraph to vis.js compatible format.

        Returns:
            dict with 'nodes' and 'edges' arrays for vis.js Network
        """
        if subgraph:
            nodes = subgraph['nodes']
            edges = subgraph['edges']
        else:
            nodes = list(self.nodes.values())
            edges = list(self.edges.values())

        vis_nodes = []
        for node in nodes:
            vis_node = {
                'id': node['node_id'],
                'label': node['labels'][0] if node.get('labels') else node['node_id'],
                'group': node['node_type'],
                'color': node.get('color', '#97C2FC'),
                'title': json.dumps(node.get('properties', {}), ensure_ascii=False, indent=2)
            }
            vis_nodes.append(vis_node)

        vis_edges = []
        for edge in edges:
            vis_edge = {
                'id': edge['edge_id'],
                'from': edge['source_node'],
                'to': edge['target_node'],
                'label': edge.get('label', edge['edge_type']),
                'arrows': 'to',
                'title': edge['edge_type']
            }
            vis_edges.append(vis_edge)

        return {
            'nodes': vis_nodes,
            'edges': vis_edges
        }


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    from pathlib import Path

    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    ONTOLOGY_DIR = PROJECT_ROOT / 'data' / 'ontology'

    nodes_path = ONTOLOGY_DIR / 'graph_nodes.jsonl'
    edges_path = ONTOLOGY_DIR / 'graph_edges.jsonl'
    schema_path = ONTOLOGY_DIR / 'schema.json'

    # Check if files exist
    if not nodes_path.exists():
        print(f"[ERROR] Nodes file not found: {nodes_path}")
        print("Run build_graph_nodes.py first.")
        exit(1)

    if not edges_path.exists():
        print(f"[ERROR] Edges file not found: {edges_path}")
        print("Run build_graph_edges.py first.")
        exit(1)

    # Load graph
    print("[INFO] Loading LPG graph...")
    graph = LPGGraph()

    if schema_path.exists():
        graph.load_schema(schema_path)
        print(f"[INFO] Schema loaded")

    stats = graph.load_from_jsonl(nodes_path, edges_path)
    print(f"[INFO] Loaded {stats['nodes']} nodes, {stats['edges']} edges")

    # Test 1: Get statistics
    print("\n[TEST 1] Graph Statistics:")
    full_stats = graph.get_statistics()
    print(f"  Node types: {full_stats['node_types']}")
    print(f"  Edge types: {full_stats['edge_types']}")

    # Test 2: Search nodes
    print("\n[TEST 2] Search nodes for '수자원':")
    results = graph.search_nodes('수자원', limit=5)
    for r in results:
        print(f"  {r['node_type']}: {r['labels'][0] if r.get('labels') else r['node_id']}")

    # Test 3: Get neighbors of a document
    doc_nodes = graph.get_nodes_by_type('Document')
    if doc_nodes:
        test_doc = doc_nodes[0]
        print(f"\n[TEST 3] Neighbors of document '{test_doc['node_id']}':")
        neighbors = graph.get_neighbors(test_doc['node_id'])
        for n in neighbors[:5]:
            print(f"  {n['direction']}: {n['node']['node_type']} via {n['edge']['edge_type']}")

    # Test 4: Get document context
    if doc_nodes:
        test_doc = doc_nodes[0]
        print(f"\n[TEST 4] Context for document '{test_doc['node_id']}':")
        context = graph.get_document_context(test_doc['node_id'])
        if context['project']:
            print(f"  Project: {context['project']['labels'][0]}")
        if context['category']:
            print(f"  Category: {context['category']['labels'][0]}")
        if context['technologies']:
            print(f"  Technologies: {[t['labels'][0] for t in context['technologies'][:3]]}")

    # Test 5: Find related documents
    if doc_nodes:
        test_doc = doc_nodes[0]
        print(f"\n[TEST 5] Related documents for '{test_doc['node_id']}':")
        related = graph.find_related_documents(test_doc['node_id'], max_results=5)
        for r in related:
            print(f"  {r['document']['labels'][0] if r['document'].get('labels') else r['document']['node_id']} (score: {r['score']:.2f})")

    # Test 6: Get subgraph
    if doc_nodes:
        test_doc = doc_nodes[0]
        print(f"\n[TEST 6] Subgraph around '{test_doc['node_id']}' (depth=2):")
        subgraph = graph.get_subgraph([test_doc['node_id']], depth=2, max_nodes=50)
        print(f"  Nodes: {subgraph['node_count']}, Edges: {subgraph['edge_count']}")

    # Test 7: Find path
    proj_nodes = graph.get_nodes_by_type('Project')
    if proj_nodes and doc_nodes:
        test_proj = proj_nodes[0]
        test_doc = doc_nodes[0]
        print(f"\n[TEST 7] Path from '{test_doc['node_id']}' to '{test_proj['node_id']}':")
        path = graph.find_path(test_doc['node_id'], test_proj['node_id'], max_depth=4)
        if path:
            for i, step in enumerate(path):
                edge_info = f" via {step['edge']['edge_type']}" if step['edge'] else ""
                print(f"  {i}: {step['node']['node_id']}{edge_info}")
        else:
            print("  No path found")

    # Test 8: Export to vis.js format
    if doc_nodes:
        test_doc = doc_nodes[0]
        print(f"\n[TEST 8] vis.js format sample:")
        subgraph = graph.get_subgraph([test_doc['node_id']], depth=1, max_nodes=10)
        vis_data = graph.to_vis_format(subgraph)
        print(f"  vis nodes: {len(vis_data['nodes'])}")
        print(f"  vis edges: {len(vis_data['edges'])}")

    print("\n[DONE] All tests completed successfully.")
