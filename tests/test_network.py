"""Tests for moltbook.network.GraphBuilder using hand-crafted interaction dicts."""

import json

import networkx as nx
import pytest

from moltbook.network import GraphBuilder


def make_interactions(pairs: list[tuple[str, str, str]], submolt: str = "test") -> list[dict]:
    """Helper: create interaction dicts from (agent, target, action) tuples."""
    return [
        {
            "action": action,
            "agent": agent,
            "target_agent": target,
            "post_id": "p1",
            "comment_id": f"c{i}",
            "parent_comment_id": None if action == "comment" else f"c{i-1}",
            "timestamp": "2024-01-01T00:00:00Z",
            "upvotes": 1,
            "submolt": submolt,
        }
        for i, (agent, target, action) in enumerate(pairs)
    ]


def make_agents(*names: str) -> dict[str, dict]:
    return {n: {"name": n, "karma": 100, "followerCount": 10, "post_count": 5} for n in names}


@pytest.fixture
def simple_graph() -> GraphBuilder:
    interactions = make_interactions([
        ("alice", "bob", "comment"),
        ("bob", "charlie", "comment"),
        ("charlie", "alice", "reply"),
        ("alice", "bob", "comment"),  # duplicate edge — weight should be 2
    ])
    agents = make_agents("alice", "bob", "charlie")
    return GraphBuilder(interactions, agents).build()


def test_build_creates_digraph(simple_graph: GraphBuilder) -> None:
    assert isinstance(simple_graph.graph, nx.DiGraph)


def test_all_nodes_have_metrics(simple_graph: GraphBuilder) -> None:
    data = simple_graph.to_json()
    required_keys = {"betweenness", "degree_centrality", "eigenvector", "in_degree", "out_degree", "community"}
    for node in data["nodes"]:
        assert required_keys.issubset(node.keys()), f"Node {node['id']} missing keys"


def test_edge_weights_positive(simple_graph: GraphBuilder) -> None:
    data = simple_graph.to_json()
    for edge in data["edges"]:
        assert edge["weight"] >= 1


def test_community_ids_assigned(simple_graph: GraphBuilder) -> None:
    data = simple_graph.to_json()
    for node in data["nodes"]:
        assert isinstance(node["community"], int)


def test_no_self_loops() -> None:
    interactions = make_interactions([
        ("alice", "alice", "comment"),  # self-loop — should be skipped
        ("alice", "bob", "comment"),
    ])
    agents = make_agents("alice", "bob")
    g = GraphBuilder(interactions, agents).build()
    assert nx.number_of_selfloops(g.graph) == 0


def test_json_serializable(simple_graph: GraphBuilder) -> None:
    data = simple_graph.to_json()
    serialized = json.dumps(data)
    assert isinstance(serialized, str)
    parsed = json.loads(serialized)
    assert "nodes" in parsed and "edges" in parsed


def test_reply_edge_direction() -> None:
    interactions = make_interactions([("alice", "bob", "reply")])
    agents = make_agents("alice", "bob")
    g = GraphBuilder(interactions, agents).build()
    data = g.to_json()
    assert len(data["edges"]) == 1
    edge = data["edges"][0]
    assert edge["source"] == "alice" and edge["target"] == "bob"


def test_weight_accumulation() -> None:
    interactions = make_interactions([
        ("alice", "bob", "comment"),
        ("alice", "bob", "reply"),
    ])
    agents = make_agents("alice", "bob")
    g = GraphBuilder(interactions, agents).build()
    data = g.to_json()
    edges_ab = [e for e in data["edges"] if e["source"] == "alice" and e["target"] == "bob"]
    assert len(edges_ab) == 1
    assert edges_ab[0]["weight"] == 2


def test_eigenvector_fallback() -> None:
    """Disconnected graph should not raise — eigenvector falls back to zeros."""
    interactions = make_interactions([
        ("alice", "bob", "comment"),
        ("charlie", "dave", "comment"),
    ])
    agents = make_agents("alice", "bob", "charlie", "dave")
    g = GraphBuilder(interactions, agents).build()
    data = g.to_json()
    assert all(isinstance(n["eigenvector"], float) for n in data["nodes"])
