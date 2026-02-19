"""Build cross-submolt reply overlap layer from observatory comment data.

Measures cross-community conversation flow using threaded replies only
(parent_id IS NOT NULL).  This is a stronger signal than top-level
comments — it captures genuine back-and-forth between communities.

Agents posting in 10+ submolts are excluded as broadcasters.

Reads:
  - data/observatory.db    (comments + posts tables)
  - data/membership.json   (agent -> home submolts via posting)

Adds reply_overlap layer to data/overlap_graphs.json.
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
MIN_REPLIES = 3
# ---------------------


def main() -> None:
    print("Loading data...")

    membership = load_membership(MEMBERSHIP_PATH)
    agent_homes = invert_membership(membership)

    total_agents = len(agent_homes)
    community_members = {
        agent: subs for agent, subs in agent_homes.items()
        if len(subs) <= MAX_HOME_SUBMOLTS
    }
    excluded = total_agents - len(community_members)
    print(f"  Community members: {len(community_members)} (excluded {excluded} broadcasters)")

    # Query DB for threaded replies with their post submolts
    print("\nQuerying observatory DB for threaded replies...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("""
        SELECT c.agent_name, p.submolt
        FROM comments c
        JOIN posts p ON c.post_id = p.id
        WHERE c.agent_name IS NOT NULL
          AND p.submolt IS NOT NULL
          AND c.parent_id IS NOT NULL
    """)

    pair_replies: dict[tuple[str, str], int] = defaultdict(int)
    submolt_total_incoming: dict[str, int] = defaultdict(int)
    submolt_total_outgoing: dict[str, int] = defaultdict(int)
    cross_replies = 0
    total_matched = 0

    for commenter, target_submolt in cursor:
        home_subs = community_members.get(commenter)
        if not home_subs:
            continue

        total_matched += 1

        for home in home_subs:
            if home != target_submolt:
                pair = tuple(sorted([home, target_submolt]))
                pair_replies[pair] += 1
                submolt_total_outgoing[home] += 1
                submolt_total_incoming[target_submolt] += 1
                cross_replies += 1

    conn.close()

    print(f"  Matched replies: {total_matched}")
    print(f"  Cross-community replies: {cross_replies}")
    print(f"  Unique submolt pairs: {len(pair_replies)}")

    # Build graph
    print(f"\nBuilding reply overlap graph (min {MIN_REPLIES} replies)...")
    G = nx.Graph()

    all_submolts = set()
    for (a, b), count in pair_replies.items():
        if count >= MIN_REPLIES:
            all_submolts.add(a)
            all_submolts.add(b)

    for sub in all_submolts:
        total = submolt_total_incoming.get(sub, 0) + submolt_total_outgoing.get(sub, 0)
        G.add_node(sub, author_count=total)

    for (a, b), count in pair_replies.items():
        if count < MIN_REPLIES:
            continue
        total_a = submolt_total_incoming.get(a, 0) + submolt_total_outgoing.get(a, 0)
        total_b = submolt_total_incoming.get(b, 0) + submolt_total_outgoing.get(b, 0)
        denom = math.sqrt(total_a * total_b) if total_a > 0 and total_b > 0 else 1
        weight = count / denom
        G.add_edge(a, b, weight=weight, shared_agents=count)

    print(f"  Nodes: {G.number_of_nodes()}")
    print(f"  Edges: {G.number_of_edges()}")

    finalize_layer(G, "reply_overlap", OUTPUT_PATH, count_label="Replies")


if __name__ == "__main__":
    main()
