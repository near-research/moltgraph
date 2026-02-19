"""Build three-layer submolt overlap network from membership data.

Reads:
  - data/membership.json      (posting membership: submolt -> [agents])
  - data/comment_membership.json (commenting membership: submolt -> [agents])

Builds three overlap graphs:
  1. post_overlap     — edges weighted by shared posters (Jaccard)
  2. comment_overlap  — edges weighted by shared commenters (Jaccard)
  3. engagement_overlap — edges weighted by shared engaged agents (union)

Outputs data/overlap_graphs.json with all three graphs.
"""

from __future__ import annotations

from collections import defaultdict

import networkx as nx

from overlap.common import (
    load_membership,
    filter_broadcasters,
    finalize_layer,
)

# --- Configuration ---
POST_MEMBERSHIP_PATH = "data/membership.json"
COMMENT_MEMBERSHIP_PATH = "data/comment_membership.json"
OUTPUT_PATH = "data/overlap_graphs.json"

MIN_AUTHORS = 1          # include all submolts with at least one agent
MAX_SUBMOLTS = 50        # broadcaster threshold
JACCARD_THRESHOLD = 0.01 # minimum Jaccard similarity to create an edge
# ---------------------


def build_engagement_membership(
    post_mem: dict[str, set[str]],
    comment_mem: dict[str, set[str]],
) -> dict[str, set[str]]:
    """Build engagement membership as union of posting and commenting per submolt."""
    all_submolts = set(post_mem.keys()) | set(comment_mem.keys())
    return {
        name: post_mem.get(name, set()) | comment_mem.get(name, set())
        for name in all_submolts
    }


def build_overlap_graph(
    membership: dict[str, set[str]],
    min_authors: int,
    jaccard_threshold: float,
) -> nx.Graph:
    """Build undirected weighted graph of submolt overlap using Jaccard similarity."""
    submolts = {name: agents for name, agents in membership.items() if len(agents) >= min_authors}
    print(f"  Submolts with >= {min_authors} agents: {len(submolts)}")

    if not submolts:
        return nx.Graph()

    # Build inverted index: agent -> set of submolts
    agent_to_submolts: dict[str, set[str]] = defaultdict(set)
    for name, agents in submolts.items():
        for agent in agents:
            agent_to_submolts[agent].add(name)

    # Count shared agents between each pair
    pair_shared: dict[tuple[str, str], int] = defaultdict(int)
    for agent, subs in agent_to_submolts.items():
        subs_list = sorted(subs)
        for i in range(len(subs_list)):
            for j in range(i + 1, len(subs_list)):
                pair_shared[(subs_list[i], subs_list[j])] += 1

    G = nx.Graph()
    for name, agents in submolts.items():
        G.add_node(name, author_count=len(agents))

    edges_added = 0
    edges_skipped = 0

    for (a, b), shared in pair_shared.items():
        union = len(submolts[a] | submolts[b])
        jaccard = shared / union if union > 0 else 0

        if jaccard >= jaccard_threshold:
            G.add_edge(a, b, weight=jaccard, shared_agents=shared)
            edges_added += 1
        else:
            edges_skipped += 1

    print(f"  Edges: {edges_added} added, {edges_skipped} below threshold")
    return G


def process_layer(label: str, membership: dict[str, set[str]]) -> dict:
    """Build one overlap layer end-to-end."""
    print(f"\n{'='*60}")
    print(f"Layer: {label}")
    print(f"{'='*60}")
    print(f"  Raw submolts: {len(membership)}")

    total_agents = set()
    for agents in membership.values():
        total_agents.update(agents)
    print(f"  Unique agents: {len(total_agents)}")

    membership = filter_broadcasters(membership, MAX_SUBMOLTS)

    print(f"  Building overlap graph (Jaccard >= {JACCARD_THRESHOLD})...")
    G = build_overlap_graph(membership, MIN_AUTHORS, JACCARD_THRESHOLD)

    return finalize_layer(G, label, OUTPUT_PATH, count_label="Agents")


def main() -> None:
    print("Loading membership data...")
    post_mem = load_membership(POST_MEMBERSHIP_PATH)
    comment_mem = load_membership(COMMENT_MEMBERSHIP_PATH)

    print(f"Posting membership: {len(post_mem)} submolts")
    print(f"Commenting membership: {len(comment_mem)} submolts")

    engagement_mem = build_engagement_membership(post_mem, comment_mem)
    print(f"Engagement membership (union): {len(engagement_mem)} submolts")

    process_layer("post_overlap", post_mem)
    process_layer("comment_overlap", comment_mem)
    process_layer("engagement_overlap", engagement_mem)


if __name__ == "__main__":
    main()
