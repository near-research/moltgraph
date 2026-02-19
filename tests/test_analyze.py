"""Tests for moltbook.analyze.NetworkAnalyzer role classification logic."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from moltbook.analyze import NetworkAnalyzer


def _write_json(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data))


@pytest.fixture
def tmp(tmp_path):
    """Provide a temp directory with minimal follow data."""
    return tmp_path


def _make_analyzer(
    tmp: Path,
    follows: list[dict] | None = None,
    agents: dict[str, dict] | None = None,
    interactions: list[dict] | None = None,
    interaction_agents: dict[str, dict] | None = None,
    membership: dict[str, list[str]] | None = None,
    overlap_nodes: list[dict] | None = None,
) -> NetworkAnalyzer:
    """Build a NetworkAnalyzer from in-memory data written to temp files."""
    follows_data = {
        "follows": follows or [],
        "agents": agents or {},
    }
    follows_path = tmp / "follows.json"
    _write_json(follows_data, follows_path)

    interactions_path = None
    if interactions is not None:
        ix_data = {
            "interactions": interactions,
            "agents": interaction_agents or {},
        }
        interactions_path = str(tmp / "interactions.json")
        _write_json(ix_data, Path(interactions_path))

    membership_path = None
    if membership is not None:
        membership_path = str(tmp / "membership.json")
        _write_json(membership, Path(membership_path))

    overlap_path = None
    if overlap_nodes is not None:
        overlap_data = {"post_overlap": {"nodes": overlap_nodes, "edges": []}}
        overlap_path = str(tmp / "overlap.json")
        _write_json(overlap_data, Path(overlap_path))

    return NetworkAnalyzer(
        follows_path=str(follows_path),
        membership_path=membership_path,
        interactions_path=interactions_path,
        overlap_graphs_path=overlap_path,
    )


# --- Fold detection ---

def test_fold_requires_two_communities(tmp):
    """Agent embedded in only 1 community is NOT a fold."""
    # 10 submolts in community 0, 10 in community 1
    overlap_nodes = (
        [{"id": f"sub_a{i}", "community": 0} for i in range(10)]
        + [{"id": f"sub_b{i}", "community": 1} for i in range(10)]
    )
    # Agent X has reciprocal interactions only in community 0
    interactions = []
    for i in range(6):
        partner = f"partner_{i}"
        interactions.append({"action": "comment", "agent": "agentX", "target_agent": partner, "submolt": "sub_a0"})
        interactions.append({"action": "comment", "agent": partner, "target_agent": "agentX", "submolt": "sub_a0"})

    membership = {"sub_a0": ["agentX"] + [f"partner_{i}" for i in range(6)]}

    a = _make_analyzer(tmp, interactions=interactions, membership=membership, overlap_nodes=overlap_nodes)
    a.analyze()
    m = a._metrics.get("agentX", {})
    assert not m.get("is_fold", False), "Agent in only 1 community should not be a fold"


def test_fold_with_two_communities(tmp):
    """Agent with reciprocal ties in 2+ communities IS a fold."""
    overlap_nodes = (
        [{"id": f"sub_a{i}", "community": 0} for i in range(10)]
        + [{"id": f"sub_b{i}", "community": 1} for i in range(10)]
    )
    interactions = []
    # 3 reciprocal partners in community 0
    for i in range(3):
        p = f"partner_a{i}"
        interactions.append({"action": "comment", "agent": "agentX", "target_agent": p, "submolt": "sub_a0"})
        interactions.append({"action": "comment", "agent": p, "target_agent": "agentX", "submolt": "sub_a0"})
    # 3 reciprocal partners in community 1
    for i in range(3):
        p = f"partner_b{i}"
        interactions.append({"action": "comment", "agent": "agentX", "target_agent": p, "submolt": "sub_b0"})
        interactions.append({"action": "comment", "agent": p, "target_agent": "agentX", "submolt": "sub_b0"})

    membership = {
        "sub_a0": ["agentX"] + [f"partner_a{i}" for i in range(3)],
        "sub_b0": ["agentX"] + [f"partner_b{i}" for i in range(3)],
    }

    a = _make_analyzer(tmp, interactions=interactions, membership=membership, overlap_nodes=overlap_nodes)
    a.analyze()
    m = a._metrics.get("agentX", {})
    assert m.get("is_fold", False), "Agent with reciprocal ties in 2+ communities should be a fold"
    assert m.get("fold_community_count", 0) >= 2
    assert "fold" in m.get("roles", [])


def test_fold_requires_five_reciprocal_ties(tmp):
    """Agent with <5 reciprocal ties is not a fold even with 2 communities."""
    overlap_nodes = (
        [{"id": f"sub_a{i}", "community": 0} for i in range(10)]
        + [{"id": f"sub_b{i}", "community": 1} for i in range(10)]
    )
    # 2 reciprocal partners in each community = 4 total (below threshold of 5)
    interactions = []
    for i in range(2):
        p = f"pa{i}"
        interactions.append({"action": "comment", "agent": "agentX", "target_agent": p, "submolt": "sub_a0"})
        interactions.append({"action": "comment", "agent": p, "target_agent": "agentX", "submolt": "sub_a0"})
    for i in range(2):
        p = f"pb{i}"
        interactions.append({"action": "comment", "agent": "agentX", "target_agent": p, "submolt": "sub_b0"})
        interactions.append({"action": "comment", "agent": p, "target_agent": "agentX", "submolt": "sub_b0"})

    membership = {
        "sub_a0": ["agentX", "pa0", "pa1"],
        "sub_b0": ["agentX", "pb0", "pb1"],
    }

    a = _make_analyzer(tmp, interactions=interactions, membership=membership, overlap_nodes=overlap_nodes)
    a.analyze()
    m = a._metrics.get("agentX", {})
    assert not m.get("is_fold", False), "Agent with <5 reciprocal ties should not be a fold"


# --- Automated fold detection ---

def test_automated_fold_karma_zero(tmp):
    """Fold with karma=0 and 1000+ interactions is flagged automated."""
    overlap_nodes = (
        [{"id": f"sub_a{i}", "community": 0} for i in range(10)]
        + [{"id": f"sub_b{i}", "community": 1} for i in range(10)]
    )
    interactions = []
    # 3 reciprocal partners per community (6 total, above threshold)
    for i in range(3):
        p = f"pa{i}"
        interactions.append({"action": "comment", "agent": "bot", "target_agent": p, "submolt": "sub_a0"})
        interactions.append({"action": "comment", "agent": p, "target_agent": "bot", "submolt": "sub_a0"})
    for i in range(3):
        p = f"pb{i}"
        interactions.append({"action": "comment", "agent": "bot", "target_agent": p, "submolt": "sub_b0"})
        interactions.append({"action": "comment", "agent": p, "target_agent": "bot", "submolt": "sub_b0"})
    # Pad to 1000+ interactions for the bot
    for i in range(1000):
        interactions.append({"action": "comment", "agent": "bot", "target_agent": f"filler{i}", "submolt": "sub_a0"})

    membership = {
        "sub_a0": ["bot"] + [f"pa{i}" for i in range(3)],
        "sub_b0": ["bot"] + [f"pb{i}" for i in range(3)],
    }
    agents = {"bot": {"name": "bot", "karma": 0}}

    a = _make_analyzer(
        tmp, interactions=interactions, interaction_agents=agents,
        membership=membership, overlap_nodes=overlap_nodes,
    )
    a.analyze()
    m = a._metrics.get("bot", {})
    assert m.get("is_fold", False)
    assert m.get("fold_automated", False), "Fold with karma=0 + 1K interactions should be automated"


def test_automated_fold_not_flagged_with_karma(tmp):
    """Fold with karma>0 should NOT be flagged automated."""
    overlap_nodes = (
        [{"id": f"sub_a{i}", "community": 0} for i in range(10)]
        + [{"id": f"sub_b{i}", "community": 1} for i in range(10)]
    )
    interactions = []
    for i in range(3):
        p = f"pa{i}"
        interactions.append({"action": "comment", "agent": "organic", "target_agent": p, "submolt": "sub_a0"})
        interactions.append({"action": "comment", "agent": p, "target_agent": "organic", "submolt": "sub_a0"})
    for i in range(3):
        p = f"pb{i}"
        interactions.append({"action": "comment", "agent": "organic", "target_agent": p, "submolt": "sub_b0"})
        interactions.append({"action": "comment", "agent": p, "target_agent": "organic", "submolt": "sub_b0"})
    for i in range(1000):
        interactions.append({"action": "comment", "agent": "organic", "target_agent": f"filler{i}", "submolt": "sub_a0"})

    membership = {
        "sub_a0": ["organic"] + [f"pa{i}" for i in range(3)],
        "sub_b0": ["organic"] + [f"pb{i}" for i in range(3)],
    }
    agents = {"organic": {"name": "organic", "karma": 50}}

    a = _make_analyzer(
        tmp, interactions=interactions, interaction_agents=agents,
        membership=membership, overlap_nodes=overlap_nodes,
    )
    a.analyze()
    m = a._metrics.get("organic", {})
    assert m.get("is_fold", False)
    assert not m.get("fold_automated", False), "Fold with karma>0 should NOT be automated"


def test_automated_fold_not_flagged_without_profile(tmp):
    """Fold without a profile entry should NOT be flagged automated (Fix 6)."""
    overlap_nodes = (
        [{"id": f"sub_a{i}", "community": 0} for i in range(10)]
        + [{"id": f"sub_b{i}", "community": 1} for i in range(10)]
    )
    interactions = []
    for i in range(3):
        p = f"pa{i}"
        interactions.append({"action": "comment", "agent": "mystery", "target_agent": p, "submolt": "sub_a0"})
        interactions.append({"action": "comment", "agent": p, "target_agent": "mystery", "submolt": "sub_a0"})
    for i in range(3):
        p = f"pb{i}"
        interactions.append({"action": "comment", "agent": "mystery", "target_agent": p, "submolt": "sub_b0"})
        interactions.append({"action": "comment", "agent": p, "target_agent": "mystery", "submolt": "sub_b0"})
    for i in range(1000):
        interactions.append({"action": "comment", "agent": "mystery", "target_agent": f"filler{i}", "submolt": "sub_a0"})

    membership = {
        "sub_a0": ["mystery"] + [f"pa{i}" for i in range(3)],
        "sub_b0": ["mystery"] + [f"pb{i}" for i in range(3)],
    }
    # No agent profile for "mystery"

    a = _make_analyzer(
        tmp, interactions=interactions,
        membership=membership, overlap_nodes=overlap_nodes,
    )
    a.analyze()
    m = a._metrics.get("mystery", {})
    assert m.get("is_fold", False)
    assert not m.get("fold_automated", False), "Agent without profile should NOT be flagged automated"


# --- Role classification ---

def test_attractor_classification(tmp):
    """Agent with 10x follower ratio and 20+ followers is an attractor."""
    follows = [{"follower": f"fan{i}", "following": "celeb"} for i in range(25)]
    follows.append({"follower": "celeb", "following": "friend"})
    agents = {"celeb": {"name": "celeb", "follower_count": 25, "following_count": 1}}

    a = _make_analyzer(tmp, follows=follows, agents=agents)
    a.analyze()
    m = a._metrics.get("celeb", {})
    assert "attractor" in m.get("roles", [])


def test_not_attractor_below_threshold(tmp):
    """Agent with <10x ratio is NOT an attractor."""
    follows = [{"follower": f"fan{i}", "following": "agent"} for i in range(15)]
    follows += [{"follower": "agent", "following": f"friend{i}"} for i in range(5)]
    agents = {"agent": {"name": "agent", "follower_count": 15, "following_count": 5}}

    a = _make_analyzer(tmp, follows=follows, agents=agents)
    a.analyze()
    m = a._metrics.get("agent", {})
    assert "attractor" not in m.get("roles", [])


def test_hub_classification(tmp):
    """Agent with 3+ mutual follows is a hub."""
    follows = []
    for i in range(4):
        follows.append({"follower": "hub_agent", "following": f"peer{i}"})
        follows.append({"follower": f"peer{i}", "following": "hub_agent"})

    a = _make_analyzer(tmp, follows=follows)
    a.analyze()
    m = a._metrics.get("hub_agent", {})
    assert "hub" in m.get("roles", [])
    assert m.get("mutual_count", 0) >= 3


def test_broadcaster_classification(tmp):
    """Agent in 5+ submolts without fold embeddedness is a broadcaster."""
    membership = {f"sub{i}": ["broadcaster_agent"] for i in range(6)}
    follows = [{"follower": "broadcaster_agent", "following": "someone"}]

    a = _make_analyzer(tmp, follows=follows, membership=membership)
    a.analyze()
    m = a._metrics.get("broadcaster_agent", {})
    assert "broadcaster" in m.get("roles", [])


def test_fold_not_broadcaster(tmp):
    """Agent that IS a fold should NOT also be a broadcaster."""
    overlap_nodes = (
        [{"id": f"sub_a{i}", "community": 0} for i in range(10)]
        + [{"id": f"sub_b{i}", "community": 1} for i in range(10)]
    )
    interactions = []
    for i in range(3):
        p = f"pa{i}"
        interactions.append({"action": "comment", "agent": "fold_agent", "target_agent": p, "submolt": "sub_a0"})
        interactions.append({"action": "comment", "agent": p, "target_agent": "fold_agent", "submolt": "sub_a0"})
    for i in range(3):
        p = f"pb{i}"
        interactions.append({"action": "comment", "agent": "fold_agent", "target_agent": p, "submolt": "sub_b0"})
        interactions.append({"action": "comment", "agent": p, "target_agent": "fold_agent", "submolt": "sub_b0"})

    membership = {f"sub_a{i}": ["fold_agent"] for i in range(3)}
    membership.update({f"sub_b{i}": ["fold_agent"] for i in range(3)})
    membership["sub_a0"] += [f"pa{i}" for i in range(3)]
    membership["sub_b0"] += [f"pb{i}" for i in range(3)]

    a = _make_analyzer(
        tmp, interactions=interactions,
        membership=membership, overlap_nodes=overlap_nodes,
    )
    a.analyze()
    m = a._metrics.get("fold_agent", {})
    assert "fold" in m.get("roles", [])
    assert "broadcaster" not in m.get("roles", []), "Folds should not be broadcasters"


# --- Empty inputs ---

def test_empty_follows(tmp):
    """Analyzer should not crash with empty follow data."""
    a = _make_analyzer(tmp)
    a.analyze()
    assert len(a._metrics) == 0


def test_report_and_json_export(tmp):
    """report() and to_json() should not crash."""
    follows = [{"follower": "a", "following": "b"}]
    a = _make_analyzer(tmp, follows=follows)
    a.analyze()

    report = a.report()
    assert "MOLTBOOK NETWORK" in report

    data = a.to_json()
    assert "agents" in data
    assert "summary" in data


# --- Bridging topology ---


def _make_fold_scenario(tmp, fold_specs):
    """Build an analyzer with fold agents bridging specified communities.

    fold_specs: list of (name, communities, tie_count) where communities is a list
    of community IDs the fold bridges. Each fold gets 3 reciprocal partners per
    community (2+ required for embeddedness) and total ties >= 5.
    """
    # 3 communities, 10 submolts each (enough for valid_communities at default min=7)
    overlap_nodes = []
    for c in range(3):
        overlap_nodes.extend([{"id": f"c{c}_s{i}", "community": c} for i in range(10)])

    interactions = []
    membership = {f"c{c}_s{i}": [] for c in range(3) for i in range(10)}

    for fold_name, comms, extra_ties in fold_specs:
        partner_idx = 0
        for c in comms:
            sub = f"c{c}_s0"
            membership[sub].append(fold_name)
            for j in range(3):  # 3 partners per community
                p = f"{fold_name}_p{partner_idx}"
                partner_idx += 1
                membership[sub].append(p)
                interactions.append({"action": "comment", "agent": fold_name, "target_agent": p, "submolt": sub})
                interactions.append({"action": "comment", "agent": p, "target_agent": fold_name, "submolt": sub})
        # Add extra interactions to reach desired tie_count if needed
        current_ties = 3 * len(comms)
        for i in range(max(0, extra_ties - current_ties)):
            sub = f"c{comms[0]}_s0"
            p = f"{fold_name}_extra{i}"
            membership[sub].append(p)
            interactions.append({"action": "comment", "agent": fold_name, "target_agent": p, "submolt": sub})
            interactions.append({"action": "comment", "agent": p, "target_agent": fold_name, "submolt": sub})

    return _make_analyzer(tmp, interactions=interactions, membership=membership, overlap_nodes=overlap_nodes)


def test_bridging_topology_basic(tmp):
    """Two folds bridging different community pairs produce correct matrix."""
    a = _make_fold_scenario(tmp, [
        ("foldA", [0, 1], 0),  # bridges communities 0 and 1
        ("foldB", [1, 2], 0),  # bridges communities 1 and 2
    ])
    a.analyze()

    bt = a._bridging
    assert bt["matrix"][(0, 1)] == 1
    assert bt["matrix"][(1, 2)] == 1
    assert (0, 2) not in bt["matrix"]  # unbridged pair
    assert len(bt["matrix"]) == 2  # 2 of 3 possible pairs bridged

    # Per-community: community 0 and 2 each connect to 1 pair, community 1 to 2
    assert bt["per_community"][1]["bridge_pairs"] == 2
    assert bt["per_community"][0]["bridge_pairs"] == 1
    assert bt["per_community"][2]["bridge_pairs"] == 1


def test_bridging_gini_uniform(tmp):
    """Uniform bridge distribution produces Gini = 0."""
    # Three folds, each bridging a different pair → 1 fold per pair, perfectly equal
    a = _make_fold_scenario(tmp, [
        ("foldA", [0, 1], 0),
        ("foldB", [1, 2], 0),
        ("foldC", [0, 2], 0),
    ])
    a.analyze()
    assert abs(a._bridging["concentration"]) < 0.01, "Uniform distribution should have Gini ≈ 0"


def test_bridging_redundancy(tmp):
    """Removing top fold by tie count disconnects the right pairs."""
    # foldA has most ties (bridges 0-1), foldB has fewer (bridges 0-1 and 1-2),
    # foldC has fewest (bridges 1-2 only)
    a = _make_fold_scenario(tmp, [
        ("foldA", [0, 1], 10),  # 10 reciprocal ties, bridges (0,1)
        ("foldB", [0, 1, 2], 7),  # 7 ties, bridges (0,1), (0,2), (1,2)
        ("foldC", [1, 2], 5),  # 5 ties, bridges (1,2)
    ])
    a.analyze()

    bt = a._bridging
    # k=1: remove foldA (10 ties) → (0,1) still has foldB, (0,2) has foldB, (1,2) has foldB+foldC
    r1 = bt["redundancy"].get(1, {})
    assert r1["disconnected_pairs"] == 0, "Removing top-1 fold should disconnect 0 pairs"

    # All 4 bridged pairs should survive with foldB still active
    total = r1["total_bridged_pairs"]
    assert r1["surviving_pairs"] == total


# --- Score-weighted metrics ---


def test_score_metrics_on_fold(tmp):
    """Fold agent gets correct score metrics from upvoted interactions."""
    overlap_nodes = (
        [{"id": f"sub_a{i}", "community": 0} for i in range(10)]
        + [{"id": f"sub_b{i}", "community": 1} for i in range(10)]
    )
    interactions = []
    # 3 reciprocal partners in community 0, some with upvotes
    for i in range(3):
        p = f"pa{i}"
        interactions.append({"agent": "agentX", "target_agent": p, "submolt": "sub_a0", "upvotes": 2})
        interactions.append({"agent": p, "target_agent": "agentX", "submolt": "sub_a0", "upvotes": 1})
    # 3 reciprocal partners in community 1, no upvotes
    for i in range(3):
        p = f"pb{i}"
        interactions.append({"agent": "agentX", "target_agent": p, "submolt": "sub_b0", "upvotes": 0})
        interactions.append({"agent": p, "target_agent": "agentX", "submolt": "sub_b0", "upvotes": 0})

    membership = {
        "sub_a0": ["agentX"] + [f"pa{i}" for i in range(3)],
        "sub_b0": ["agentX"] + [f"pb{i}" for i in range(3)],
    }

    a = _make_analyzer(tmp, interactions=interactions, membership=membership, overlap_nodes=overlap_nodes)
    a.analyze()
    m = a._metrics.get("agentX", {})

    assert m.get("is_fold")
    assert m["total_upvotes"] == 6  # 3 interactions * 2 upvotes each
    assert m["interaction_count"] == 6  # agentX commented 6 times
    assert m["upvotes_per_interaction"] == 1.0  # 6/6
    # Reciprocal tie score: pa partners have 2+1=3 per pair, pb partners have 0
    assert m["reciprocal_tie_score"] == 9  # 3 pairs * 3
    assert m["scored_reciprocal_tie_count"] == 3  # only pa partners have score


def test_score_metrics_zero_interactions(tmp):
    """Agent with no interactions gets zero score metrics."""
    follows = [{"follower": "a", "following": "b"}]
    a = _make_analyzer(tmp, follows=follows)
    a.analyze()
    m = a._metrics.get("a", {})
    assert m.get("total_upvotes") == 0
    assert m.get("interaction_count") == 0
    assert m.get("upvotes_per_interaction") == 0.0


def test_score_diagnostics_filters_unscored_folds(tmp):
    """Score diagnostic correctly identifies folds that lose status without upvote signal."""
    overlap_nodes = (
        [{"id": f"sub_a{i}", "community": 0} for i in range(10)]
        + [{"id": f"sub_b{i}", "community": 1} for i in range(10)]
    )
    interactions = []
    # foldA: all reciprocal ties have upvotes → survives score filtering
    for i in range(3):
        p = f"foldA_pa{i}"
        interactions.append({"agent": "foldA", "target_agent": p, "submolt": "sub_a0", "upvotes": 1})
        interactions.append({"agent": p, "target_agent": "foldA", "submolt": "sub_a0", "upvotes": 0})
    for i in range(3):
        p = f"foldA_pb{i}"
        interactions.append({"agent": "foldA", "target_agent": p, "submolt": "sub_b0", "upvotes": 1})
        interactions.append({"agent": p, "target_agent": "foldA", "submolt": "sub_b0", "upvotes": 0})

    # foldB: NO upvotes on any ties → lost under score filtering
    for i in range(3):
        p = f"foldB_pa{i}"
        interactions.append({"agent": "foldB", "target_agent": p, "submolt": "sub_a0", "upvotes": 0})
        interactions.append({"agent": p, "target_agent": "foldB", "submolt": "sub_a0", "upvotes": 0})
    for i in range(3):
        p = f"foldB_pb{i}"
        interactions.append({"agent": "foldB", "target_agent": p, "submolt": "sub_b0", "upvotes": 0})
        interactions.append({"agent": p, "target_agent": "foldB", "submolt": "sub_b0", "upvotes": 0})

    membership = {
        "sub_a0": ["foldA", "foldB"] + [f"foldA_pa{i}" for i in range(3)] + [f"foldB_pa{i}" for i in range(3)],
        "sub_b0": ["foldA", "foldB"] + [f"foldA_pb{i}" for i in range(3)] + [f"foldB_pb{i}" for i in range(3)],
    }

    a = _make_analyzer(tmp, interactions=interactions, membership=membership, overlap_nodes=overlap_nodes)
    a.analyze()

    assert a._metrics["foldA"]["is_fold"]
    assert a._metrics["foldB"]["is_fold"]

    d = a._score_diagnostics
    assert d["original_folds"] == 2
    assert d["scored_folds"] == 1
    assert "foldB" in d["lost"]
    assert "foldA" not in d["lost"]


# --- Temporal fold formation ---


def test_temporal_fold_formation(tmp):
    """Fold appearing on day 2 gets correct first_fold_date."""
    overlap_nodes = (
        [{"id": f"sub_a{i}", "community": 0} for i in range(10)]
        + [{"id": f"sub_b{i}", "community": 1} for i in range(10)]
    )
    # Day 1: agentX gets 3 partners in community 0 only (not yet a fold)
    interactions = []
    for i in range(3):
        p = f"pa{i}"
        interactions.append({
            "agent": "agentX", "target_agent": p, "submolt": "sub_a0",
            "timestamp": "2026-02-04T10:00:00+00:00",
        })
        interactions.append({
            "agent": p, "target_agent": "agentX", "submolt": "sub_a0",
            "timestamp": "2026-02-04T11:00:00+00:00",
        })

    # Day 2: agentX gets 3 partners in community 1 (now a fold: 6 ties, 2 communities)
    for i in range(3):
        p = f"pb{i}"
        interactions.append({
            "agent": "agentX", "target_agent": p, "submolt": "sub_b0",
            "timestamp": "2026-02-05T10:00:00+00:00",
        })
        interactions.append({
            "agent": p, "target_agent": "agentX", "submolt": "sub_b0",
            "timestamp": "2026-02-05T11:00:00+00:00",
        })

    membership = {
        "sub_a0": ["agentX"] + [f"pa{i}" for i in range(3)],
        "sub_b0": ["agentX"] + [f"pb{i}" for i in range(3)],
    }

    a = _make_analyzer(tmp, interactions=interactions, membership=membership, overlap_nodes=overlap_nodes)
    a.analyze()

    m = a._metrics.get("agentX", {})
    assert m.get("is_fold")
    assert m.get("first_fold_date") == "2026-02-05", f"Expected 2026-02-05, got {m.get('first_fold_date')}"

    # Timeline should show 0 folds on day 1, 1 fold on day 2
    tl = a._temporal_folds["timeline"]
    assert len(tl) == 2
    assert tl[0]["fold_count"] == 0
    assert tl[1]["fold_count"] == 1
    assert tl[1]["new_folds"] == 1


def test_temporal_no_timestamps(tmp):
    """Interactions without timestamps produce empty temporal_folds, no crash."""
    overlap_nodes = (
        [{"id": f"sub_a{i}", "community": 0} for i in range(10)]
        + [{"id": f"sub_b{i}", "community": 1} for i in range(10)]
    )
    interactions = []
    for i in range(3):
        p = f"pa{i}"
        interactions.append({"agent": "agentX", "target_agent": p, "submolt": "sub_a0"})
        interactions.append({"agent": p, "target_agent": "agentX", "submolt": "sub_a0"})
    for i in range(3):
        p = f"pb{i}"
        interactions.append({"agent": "agentX", "target_agent": p, "submolt": "sub_b0"})
        interactions.append({"agent": p, "target_agent": "agentX", "submolt": "sub_b0"})

    membership = {
        "sub_a0": ["agentX"] + [f"pa{i}" for i in range(3)],
        "sub_b0": ["agentX"] + [f"pb{i}" for i in range(3)],
    }

    a = _make_analyzer(tmp, interactions=interactions, membership=membership, overlap_nodes=overlap_nodes)
    a.analyze()

    assert a._temporal_folds == {}
    assert a._metrics["agentX"]["is_fold"]


def test_bridging_empty(tmp):
    """No folds → empty bridging topology, no crash."""
    # Only broadcasters, no fold-eligible agents
    membership = {f"sub{i}": ["loner"] for i in range(6)}
    a = _make_analyzer(tmp, membership=membership)
    a.analyze()

    bt = a._bridging
    assert len(bt["matrix"]) == 0
    assert bt["concentration"] == 0.0


def test_is_claimed_merge_preserves_observatory(tmp):
    """Observatory is_claimed=False must survive API merge that sets is_claimed=True."""
    overlap_nodes = (
        [{"id": f"sub_a{i}", "community": 0} for i in range(10)]
        + [{"id": f"sub_b{i}", "community": 1} for i in range(10)]
    )
    # Observatory agent has is_claimed=False (the ground truth)
    interaction_agents = {
        "botAgent": {"name": "botAgent", "is_claimed": False, "karma": 0},
    }
    # API follows agent has is_claimed=True (unreliable, should be overwritten)
    api_agents = {
        "botAgent": {"name": "botAgent", "is_claimed": True, "karma": 5, "followerCount": 10},
    }
    interactions = [
        {"agent": "botAgent", "target_agent": "other", "submolt": "sub_a0"},
    ]
    membership = {"sub_a0": ["botAgent", "other"]}

    a = _make_analyzer(
        tmp,
        agents=api_agents,
        interactions=interactions,
        interaction_agents=interaction_agents,
        membership=membership,
        overlap_nodes=overlap_nodes,
    )
    a.analyze()
    m = a._metrics.get("botAgent", {})
    assert m.get("is_claimed") is False, (
        "Observatory is_claimed=False should survive API merge"
    )


def test_follower_ratio_zero_following(tmp):
    """Agent with followers but following nobody should get a valid follower_ratio."""
    follows = [
        {"follower": "fan1", "following": "popular"},
        {"follower": "fan2", "following": "popular"},
        {"follower": "fan3", "following": "popular"},
    ]
    agents = {
        "popular": {"name": "popular", "followerCount": 0, "followingCount": 0},
        "fan1": {"name": "fan1"},
        "fan2": {"name": "fan2"},
        "fan3": {"name": "fan3"},
    }
    a = _make_analyzer(tmp, follows=follows, agents=agents)
    a.analyze()
    m = a._metrics.get("popular", {})
    # popular has 3 graph followers but API says 0 — with the fix, API 0 is used (not None)
    # follower_ratio with following_count=0 should use the capped branch
    assert isinstance(m.get("follower_ratio"), (int, float)), "follower_ratio should be numeric"
    assert m["following_count"] == 0, "API followingCount=0 should be preserved, not overridden"
    assert m["follower_count"] == 0, "API followerCount=0 should be preserved, not overridden"


def test_self_interaction_not_reciprocal(tmp):
    """Self-interactions (agent == target_agent) must not create false reciprocal ties."""
    overlap_nodes = [{"id": f"sub{i}", "community": 0} for i in range(10)]
    # Agent interacts with itself — should NOT count as a reciprocal tie
    interactions = [
        {"action": "comment", "agent": "selfie", "target_agent": "selfie", "submolt": "sub0"},
        {"action": "comment", "agent": "selfie", "target_agent": "selfie", "submolt": "sub0"},
    ]
    membership = {"sub0": ["selfie"]}

    a = _make_analyzer(tmp, interactions=interactions, membership=membership, overlap_nodes=overlap_nodes)
    a.analyze()
    m = a._metrics.get("selfie", {})
    assert m.get("reciprocal_tie_count", 0) == 0, "Self-interactions should not create reciprocal ties"
