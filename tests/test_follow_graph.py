"""Tests for moltbook.network.FollowGraphBuilder."""

import json

import networkx as nx
import pytest

from moltbook.network import FollowGraphBuilder


def make_follows(pairs: list[tuple[str, str]]) -> list[dict]:
    return [{"follower": a, "following": b} for a, b in pairs]


def make_agents(*names: str) -> dict[str, dict]:
    return {n: {"name": n, "karma": 10, "follower_count": 5, "following_count": 3} for n in names}


@pytest.fixture
def simple_follow_graph() -> FollowGraphBuilder:
    follows = make_follows([
        ("alice", "bob"),
        ("bob", "alice"),   # mutual
        ("bob", "charlie"),
        ("charlie", "dave"),
    ])
    agents = make_agents("alice", "bob", "charlie", "dave")
    return FollowGraphBuilder(follows, agents).build()


def test_build_creates_digraph(simple_follow_graph):
    assert isinstance(simple_follow_graph.graph, nx.DiGraph)


def test_mutual_detection(simple_follow_graph):
    data = simple_follow_graph.to_json()
    ab_edges = [e for e in data["edges"] if e["source"] == "alice" and e["target"] == "bob"]
    assert len(ab_edges) == 1
    assert ab_edges[0]["mutual"] is True

    bc_edges = [e for e in data["edges"] if e["source"] == "bob" and e["target"] == "charlie"]
    assert len(bc_edges) == 1
    assert bc_edges[0]["mutual"] is False


def test_graph_type_marker(simple_follow_graph):
    data = simple_follow_graph.to_json()
    assert data["graph_type"] == "follow"


def test_all_nodes_have_metrics(simple_follow_graph):
    data = simple_follow_graph.to_json()
    required = {"betweenness", "degree_centrality", "eigenvector", "community", "in_degree", "out_degree"}
    for node in data["nodes"]:
        assert required.issubset(node.keys()), f"Node {node['id']} missing keys"


def test_no_self_loops():
    follows = make_follows([("alice", "alice"), ("alice", "bob")])
    agents = make_agents("alice", "bob")
    g = FollowGraphBuilder(follows, agents).build()
    assert nx.number_of_selfloops(g.graph) == 0


def test_json_serializable(simple_follow_graph):
    data = simple_follow_graph.to_json()
    serialized = json.dumps(data)
    parsed = json.loads(serialized)
    assert "nodes" in parsed and "edges" in parsed


def test_empty_follows():
    g = FollowGraphBuilder([], {}).build()
    data = g.to_json()
    assert len(data["nodes"]) == 0
    assert len(data["edges"]) == 0
