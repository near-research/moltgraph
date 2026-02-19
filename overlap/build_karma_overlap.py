"""Build karma-weighted submolt overlap layer.

Replaces unweighted Jaccard with a weighted variant where each agent's
contribution is log2(karma + 2).  High-reputation agents count more,
surfacing overlap between communities that share influential members
rather than lurkers.

Reads:
  - data/membership.json       (submolt -> [agents])
  - data/observatory.db        (agents table for karma)

Adds karma_overlap layer to data/overlap_graphs.json.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict

import networkx as nx

from overlap.common import load_membership, filter_broadcasters, finalize_layer

# --- Configuration ---
MEMBERSHIP_PATH = "data/membership.json"
DB_PATH = "data/observatory.db"
OUTPUT_PATH = "data/overlap_graphs.json"

MAX_SUBMOLTS = 50
JACCARD_THRESHOLD = 0.01
# ---------------------


def load_karma(db_path: str) -> dict[str, float]:
    """Load agent karma from observatory DB, return log-scaled weights."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT name, karma FROM agents WHERE name IS NOT NULL").fetchall()
    conn.close()
    return {name: math.log2(max(karma or 0, 0) + 2) for name, karma in rows}


def main() -> None:
    print("Loading data...")
    membership = load_membership(MEMBERSHIP_PATH)
    karma_weights = load_karma(DB_PATH)
    print(f"  Membership: {len(membership)} submolts")
    print(f"  Karma weights: {len(karma_weights)} agents")

    membership = filter_broadcasters(membership, MAX_SUBMOLTS)

    # Build inverted index
    agent_to_submolts: dict[str, set[str]] = defaultdict(set)
    for name, agents in membership.items():
        for agent in agents:
            agent_to_submolts[agent].add(name)

    # Count shared agents per pair
    pair_shared: dict[tuple[str, str], set[str]] = defaultdict(set)
    for agent, subs in agent_to_submolts.items():
        subs_list = sorted(subs)
        for i in range(len(subs_list)):
            for j in range(i + 1, len(subs_list)):
                pair_shared[(subs_list[i], subs_list[j])].add(agent)

    # Build graph with karma-weighted Jaccard edges
    G = nx.Graph()
    for name, agents in membership.items():
        if agents:
            G.add_node(name, author_count=len(agents))

    edges_added = 0
    edges_skipped = 0

    for (a, b), shared_agents in pair_shared.items():
        union_agents = membership[a] | membership[b]
        numerator = sum(karma_weights.get(ag, 1.0) for ag in shared_agents)
        denominator = sum(karma_weights.get(ag, 1.0) for ag in union_agents)
        weighted_jaccard = numerator / denominator if denominator > 0 else 0

        if weighted_jaccard >= JACCARD_THRESHOLD:
            G.add_edge(a, b, weight=weighted_jaccard, shared_agents=len(shared_agents))
            edges_added += 1
        else:
            edges_skipped += 1

    print(f"  Edges: {edges_added} added, {edges_skipped} below threshold")

    finalize_layer(G, "karma_overlap", OUTPUT_PATH, count_label="Agents")


if __name__ == "__main__":
    main()
