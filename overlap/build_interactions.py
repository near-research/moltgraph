"""Build interaction overlap layer from observatory comment data.

Measures actual cross-community information flow: when an agent who
posts in submolt A comments on a post in submolt B, that's a
cross-community interaction.

Agents posting in 10+ submolts are excluded — they're broadcasters,
not identifiable community members.

Reads:
  - data/observatory.db    (posts + comments tables)
  - data/membership.json   (agent -> home submolts via posting)

Adds interaction_overlap layer to data/overlap_graphs.json.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict

import networkx as nx

from overlap.common import load_membership, invert_membership, finalize_layer

# --- Configuration ---
DB_PATH = "data/observatory.db"
MEMBERSHIP_PATH = "data/membership.json"
OUTPUT_PATH = "data/overlap_graphs.json"

MAX_HOME_SUBMOLTS = 10
MIN_INTERACTIONS = 2
# ---------------------


def main() -> None:
    print("Loading observatory data from DB...")

    conn = sqlite3.connect(DB_PATH)

    # Build post_id -> submolt mapping
    post_rows = conn.execute(
        "SELECT id, submolt FROM posts WHERE id IS NOT NULL AND submolt IS NOT NULL"
    ).fetchall()
    post_submolt: dict[str, str] = {pid: sub for pid, sub in post_rows}
    print(f"  Posts with submolt: {len(post_submolt)}")

    # Load membership and invert to agent -> submolts
    membership = load_membership(MEMBERSHIP_PATH)
    agent_homes = invert_membership(membership)

    total_agents = len(agent_homes)
    community_members = {
        agent: subs for agent, subs in agent_homes.items()
        if len(subs) <= MAX_HOME_SUBMOLTS
    }
    excluded = total_agents - len(community_members)
    print(f"  Community members: {len(community_members)} (excluded {excluded} broadcasters posting in >{MAX_HOME_SUBMOLTS} submolts)")

    # Process comments: count cross-community interactions
    print("\nCounting cross-community interactions...")
    pair_interactions: dict[tuple[str, str], int] = defaultdict(int)
    submolt_total_incoming: dict[str, int] = defaultdict(int)
    submolt_total_outgoing: dict[str, int] = defaultdict(int)
    cross_comments = 0
    total_matched = 0

    cursor = conn.execute(
        "SELECT agent_name, post_id FROM comments WHERE agent_name IS NOT NULL AND post_id IS NOT NULL"
    )

    for commenter, post_id in cursor:
        target_submolt = post_submolt.get(post_id)
        if not target_submolt:
            continue
        home_subs = community_members.get(commenter)
        if not home_subs:
            continue

        total_matched += 1

        for home in home_subs:
            if home != target_submolt:
                pair = tuple(sorted([home, target_submolt]))
                pair_interactions[pair] += 1
                submolt_total_outgoing[home] += 1
                submolt_total_incoming[target_submolt] += 1
                cross_comments += 1

    conn.close()

    print(f"  Matched comments: {total_matched}")
    print(f"  Cross-community interactions: {cross_comments}")
    print(f"  Unique submolt pairs with interactions: {len(pair_interactions)}")

    # Build graph
    print(f"\nBuilding interaction overlap graph (min {MIN_INTERACTIONS} interactions)...")
    G = nx.Graph()

    all_submolts = set()
    for (a, b), count in pair_interactions.items():
        if count >= MIN_INTERACTIONS:
            all_submolts.add(a)
            all_submolts.add(b)

    for sub in all_submolts:
        total = submolt_total_incoming.get(sub, 0) + submolt_total_outgoing.get(sub, 0)
        G.add_node(sub, author_count=total)

    for (a, b), count in pair_interactions.items():
        if count < MIN_INTERACTIONS:
            continue
        total_a = submolt_total_incoming.get(a, 0) + submolt_total_outgoing.get(a, 0)
        total_b = submolt_total_incoming.get(b, 0) + submolt_total_outgoing.get(b, 0)
        denom = math.sqrt(total_a * total_b) if total_a > 0 and total_b > 0 else 1
        weight = count / denom
        G.add_edge(a, b, weight=weight, shared_agents=count)

    print(f"  Nodes: {G.number_of_nodes()}")
    print(f"  Edges: {G.number_of_edges()}")

    finalize_layer(G, "interaction_overlap", OUTPUT_PATH, count_label="Interactions")


if __name__ == "__main__":
    main()
