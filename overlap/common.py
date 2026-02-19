"""Shared utilities for the overlap analysis pipeline.

Provides graph building, community detection, centrality metrics,
export, and membership loading — used by all build_*.py scripts.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import networkx as nx
from networkx.algorithms.community import greedy_modularity_communities

DEFAULT_OUTPUT = "data/overlap_graphs.json"


def load_membership(path: str) -> dict[str, set[str]]:
    """Load membership data and return {submolt: set of agent names}."""
    p = Path(path)
    if not p.exists():
        print(f"  {path} not found, returning empty")
        return {}
    raw = json.loads(p.read_text())
    return {name: set(agents) for name, agents in raw.items()}


def filter_broadcasters(
    membership: dict[str, set[str]],
    max_submolts: int,
) -> dict[str, set[str]]:
    """Remove agents who appear in too many submolts (universal broadcasters)."""
    agent_counts: dict[str, int] = defaultdict(int)
    for agents in membership.values():
        for agent in agents:
            agent_counts[agent] += 1

    broadcasters = {a for a, c in agent_counts.items() if c > max_submolts}
    total_agents = len(agent_counts)

    if broadcasters:
        print(f"  Filtering {len(broadcasters)} broadcasters (>{max_submolts} submolts) from {total_agents} total agents")
        return {name: agents - broadcasters for name, agents in membership.items()}

    return membership


def invert_membership(membership: dict[str, set[str]]) -> dict[str, set[str]]:
    """Build agent -> set of submolts from submolt -> set of agents."""
    agent_to_submolts: dict[str, set[str]] = defaultdict(set)
    for name, agents in membership.items():
        for agent in agents:
            agent_to_submolts[agent].add(name)
    return dict(agent_to_submolts)


def detect_communities(G: nx.Graph) -> dict[str, int]:
    """Run greedy modularity community detection on the overlap graph."""
    if G.number_of_nodes() == 0:
        return {}

    try:
        communities = list(greedy_modularity_communities(G, weight="weight"))
    except ValueError:
        communities = [set(G.nodes())]

    mapping = {}
    for i, comm in enumerate(communities):
        for node in comm:
            mapping[node] = i
    return mapping


def compute_metrics(G: nx.Graph) -> tuple[dict, dict]:
    """Compute betweenness and degree centrality."""
    if G.number_of_nodes() == 0:
        return {}, {}
    betweenness = nx.betweenness_centrality(G, weight="weight", normalized=True)
    degree = nx.degree_centrality(G)
    return betweenness, degree


def graph_to_dict(
    G: nx.Graph,
    communities: dict[str, int],
    betweenness: dict,
    degree: dict,
) -> dict:
    """Export overlap graph as JSON-serializable dict."""
    nodes = []
    for name in G.nodes():
        nodes.append({
            "id": name,
            "author_count": G.nodes[name].get("author_count", 0),
            "community": communities.get(name, -1),
            "betweenness": round(betweenness.get(name, 0), 6),
            "degree_centrality": round(degree.get(name, 0), 6),
            "degree": G.degree(name),
        })

    edges = []
    for u, v, data in G.edges(data=True):
        edges.append({
            "source": u,
            "target": v,
            "weight": round(data["weight"], 6),
            "shared_agents": data["shared_agents"],
        })

    return {"nodes": nodes, "edges": edges}


def finalize_layer(
    G: nx.Graph,
    layer_name: str,
    output_path: str = DEFAULT_OUTPUT,
    top_n: int = 15,
    count_label: str = "Agents",
) -> dict:
    """Detect communities, compute metrics, export, save, and print summary."""
    print(f"  Detecting communities...")
    communities = detect_communities(G)
    n_communities = len(set(communities.values())) if communities else 0
    print(f"  Found {n_communities} communities")

    print(f"  Computing metrics...")
    betweenness, degree = compute_metrics(G)

    graph_data = graph_to_dict(G, communities, betweenness, degree)
    graph_data["layer"] = layer_name

    print(f"  Result: {len(graph_data['nodes'])} nodes, {len(graph_data['edges'])} edges")

    # Print top bridges
    top = sorted(graph_data["nodes"], key=lambda n: n["betweenness"], reverse=True)[:top_n]
    if top:
        print(f"\n  Top {top_n} bridges ({layer_name}):")
        print(f"  {'':<30}{count_label:>12}{'Degree':>8}{'Comm':>6}{'Between':>10}")
        print(f"  {'-'*66}")
        for n in top:
            print(f"  {n['id']:<30}{n['author_count']:>12}{n['degree']:>8}{n['community']:>6}{n['betweenness']:>10.4f}")

    # Merge into existing output
    out_path = Path(output_path)
    if out_path.exists():
        layers = json.loads(out_path.read_text())
    else:
        layers = {}
        out_path.parent.mkdir(parents=True, exist_ok=True)

    layers[layer_name] = graph_data
    out_path.write_text(json.dumps(layers, indent=2))

    print(f"\n  Saved {layer_name}: {len(graph_data['nodes'])} nodes, {len(graph_data['edges'])} edges -> {out_path}")
    return graph_data
