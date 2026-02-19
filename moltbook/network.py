"""Build directed weighted graphs from Moltbook interactions or follow relationships."""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
from networkx.algorithms.community import greedy_modularity_communities


class _GraphBuilderBase:
    """Shared community detection and centrality computation for graph builders."""

    # Threshold for switching to approximate algorithms
    LARGE_GRAPH_THRESHOLD = 5000

    def __init__(self) -> None:
        self.graph: nx.DiGraph = nx.DiGraph()
        self._communities: dict[str, int] = {}
        self._betweenness: dict[str, float] = {}
        self._degree: dict[str, float] = {}
        self._eigenvector: dict[str, float] = {}

    def _detect_communities(self) -> None:
        """Run community detection on the undirected projection.

        Uses Louvain for large graphs (fast, O(n log n)), greedy modularity for small ones.
        """
        undirected = self.graph.to_undirected()
        n = undirected.number_of_nodes()

        try:
            if n > self.LARGE_GRAPH_THRESHOLD:
                print(f"  Large graph ({n} nodes) — using Louvain community detection")
                communities = list(nx.community.louvain_communities(
                    undirected, weight="weight", seed=42,
                ))
            else:
                communities = list(greedy_modularity_communities(undirected, weight="weight"))
        except (ValueError, ZeroDivisionError, nx.NetworkXError) as exc:
            print(f"Warning: community detection failed ({exc}), assigning all nodes to one community")
            communities = [set(self.graph.nodes())]

        self._communities = {}
        for i, community in enumerate(communities):
            for node in community:
                self._communities[node] = i

        for node in self.graph.nodes():
            if node not in self._communities:
                self._communities[node] = -1

        print(f"  {len(communities)} communities detected")

    def _compute_metrics(self) -> None:
        """Compute centrality measures for all nodes.

        Uses approximate betweenness (k=500 sample) for large graphs.
        """
        G = self.graph
        n = G.number_of_nodes()

        if n > self.LARGE_GRAPH_THRESHOLD:
            k = min(500, n)
            print(f"  Large graph ({n} nodes) — using approximate betweenness (k={k})")
            self._betweenness = nx.betweenness_centrality(G, weight="weight", normalized=True, k=k)
        else:
            self._betweenness = nx.betweenness_centrality(G, weight="weight", normalized=True)

        self._degree = nx.degree_centrality(G)

        try:
            self._eigenvector = nx.eigenvector_centrality(G, weight="weight", max_iter=1000)
        except (nx.PowerIterationFailedConvergence, nx.NetworkXError):
            print("Warning: eigenvector centrality did not converge, falling back to degree centrality")
            self._eigenvector = dict(self._degree)


class GraphBuilder(_GraphBuilderBase):
    """Builds a networkx DiGraph from interaction dicts, computes centrality and communities."""

    def __init__(self, interactions: list[dict], agents: dict[str, dict]) -> None:
        super().__init__()
        self._interactions = interactions
        self._agents = agents

    def build(self) -> GraphBuilder:
        """Build the graph, detect communities, compute metrics. Returns self for chaining."""
        G = self.graph

        for ix in self._interactions:
            source = ix.get("agent")
            target = ix.get("target_agent")

            if not source or not target or source == target:
                continue

            G.add_node(source)
            G.add_node(target)

            if G.has_edge(source, target):
                G[source][target]["weight"] += 1
                G[source][target]["upvotes"] += ix.get("upvotes", 0)
                G[source][target]["submolts"].add(ix.get("submolt", ""))
            else:
                G.add_edge(
                    source, target,
                    weight=1,
                    upvotes=ix.get("upvotes", 0),
                    submolts={ix.get("submolt", "")},
                )

        if G.number_of_nodes() > 0:
            self._detect_communities()
            self._compute_metrics()

        return self

    def to_json(self) -> dict:
        """Export graph as JSON dict with nodes array and edges array."""
        G = self.graph

        nodes = []
        for name in G.nodes():
            agent = self._agents.get(name, {})
            nodes.append({
                "id": name,
                "display_name": agent.get("name", name),
                "karma": agent.get("karma", 0),
                "follower_count": agent.get("followerCount", agent.get("follower_count", 0)),
                "post_count": agent.get("post_count", 0),
                "community": self._communities.get(name, -1),
                "betweenness": round(self._betweenness.get(name, 0), 6),
                "degree_centrality": round(self._degree.get(name, 0), 6),
                "eigenvector": round(self._eigenvector.get(name, 0), 6),
                "in_degree": G.in_degree(name),
                "out_degree": G.out_degree(name),
            })

        edges = []
        for u, v, data in G.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "weight": data["weight"],
                "upvotes": data.get("upvotes", 0),
                "submolts": sorted(data.get("submolts", set())),
            })

        return {"graph_type": "interaction", "nodes": nodes, "edges": edges}

    def save_json(self, path: str) -> None:
        """Write graph JSON to disk."""
        graph_data = self.to_json()
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(graph_data, indent=2))
        print(f"Graph: {len(graph_data['nodes'])} nodes, {len(graph_data['edges'])} edges → {out_path}")


class FollowGraphBuilder(_GraphBuilderBase):
    """Builds a networkx DiGraph from follow relationships with mutual follow detection."""

    def __init__(self, follows: list[dict], agents: dict[str, dict]) -> None:
        super().__init__()
        self._follows = follows
        self._agents = agents

    def build(self) -> FollowGraphBuilder:
        """Build the follow graph, detect mutual follows, communities, and metrics."""
        G = self.graph

        for f in self._follows:
            follower = f.get("follower")
            following = f.get("following")
            if not follower or not following or follower == following:
                continue
            G.add_node(follower)
            G.add_node(following)
            G.add_edge(follower, following, weight=1)

        # Mark mutual follows
        for u, v in list(G.edges()):
            G[u][v]["mutual"] = G.has_edge(v, u)

        if G.number_of_nodes() > 0:
            self._detect_communities()
            self._compute_metrics()

        return self

    def to_json(self) -> dict:
        """Export follow graph as JSON with graph_type marker and mutual flags."""
        G = self.graph

        nodes = []
        for name in G.nodes():
            agent = self._agents.get(name, {})
            nodes.append({
                "id": name,
                "display_name": agent.get("name", name),
                "karma": agent.get("karma", 0),
                "follower_count": agent.get("followerCount", agent.get("follower_count", 0)),
                "following_count": agent.get("followingCount", agent.get("following_count", 0)),
                "community": self._communities.get(name, -1),
                "betweenness": round(self._betweenness.get(name, 0), 6),
                "degree_centrality": round(self._degree.get(name, 0), 6),
                "eigenvector": round(self._eigenvector.get(name, 0), 6),
                "in_degree": G.in_degree(name),
                "out_degree": G.out_degree(name),
            })

        edges = []
        for u, v, data in G.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "weight": data["weight"],
                "mutual": data.get("mutual", False),
            })

        return {"graph_type": "follow", "nodes": nodes, "edges": edges}

    def save_json(self, path: str) -> None:
        """Write follow graph JSON to disk."""
        graph_data = self.to_json()
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(graph_data, indent=2))
        mutual_count = sum(1 for e in graph_data["edges"] if e["mutual"]) // 2
        print(f"Follow graph: {len(graph_data['nodes'])} nodes, {len(graph_data['edges'])} edges, {mutual_count} mutual pairs → {out_path}")
