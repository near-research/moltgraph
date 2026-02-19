"""Build temporal overlap layer from observatory post timestamps.

Builds hourly activity vectors per submolt and computes pairwise cosine
similarity.  Submolts with synchronized posting bursts get high edge
weight even if they share no agents — revealing coordinated activity or
strong topical alignment.

Reads:
  - data/observatory.db  (posts table with created_at timestamps)

Adds temporal_overlap layer to data/overlap_graphs.json.
"""

from __future__ import annotations

import sqlite3

import networkx as nx
import numpy as np

from overlap.common import finalize_layer

# --- Configuration ---
DB_PATH = "data/observatory.db"
OUTPUT_PATH = "data/overlap_graphs.json"

MIN_TOTAL_POSTS = 10
COSINE_THRESHOLD = 0.3
SKIP = {"general", "mbc20", "mbc-20", "mbc20-mint"}
# ---------------------


def main() -> None:
    print("Loading post timestamps from observatory DB...")
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT submolt, strftime('%Y-%m-%d %H', created_at) as hour_bucket, COUNT(*) as n
        FROM posts
        WHERE created_at IS NOT NULL AND submolt IS NOT NULL
        GROUP BY submolt, hour_bucket
    """).fetchall()
    conn.close()

    # Build per-submolt activity dicts
    submolt_activity: dict[str, dict[str, int]] = {}
    submolt_totals: dict[str, int] = {}
    all_hours: set[str] = set()

    for submolt, hour, count in rows:
        if submolt in SKIP:
            continue
        if submolt not in submolt_activity:
            submolt_activity[submolt] = {}
            submolt_totals[submolt] = 0
        submolt_activity[submolt][hour] = count
        submolt_totals[submolt] += count
        all_hours.add(hour)

    # Filter by minimum posts
    submolt_activity = {
        s: v for s, v in submolt_activity.items()
        if submolt_totals[s] >= MIN_TOTAL_POSTS
    }

    submolts = sorted(submolt_activity.keys())
    hours = sorted(all_hours)
    n_submolts = len(submolts)
    n_hours = len(hours)

    print(f"  Submolts (>={MIN_TOTAL_POSTS} posts, excl. noise): {n_submolts}")
    print(f"  Hour buckets: {n_hours}")

    if n_submolts < 2:
        print("  Not enough submolts for pairwise comparison")
        return

    # Build activity matrix (submolts x hours)
    hour_idx = {h: i for i, h in enumerate(hours)}
    matrix = np.zeros((n_submolts, n_hours), dtype=np.float64)

    for i, sub in enumerate(submolts):
        for hour, count in submolt_activity[sub].items():
            matrix[i, hour_idx[hour]] = count

    # Compute cosine similarity matrix
    print("\nComputing cosine similarity matrix...")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    normalized = matrix / norms
    sim_matrix = normalized @ normalized.T

    # Count co-occurrence hours per pair
    active_mask = (matrix > 0).astype(np.float64)
    cooccurrence = (active_mask @ active_mask.T).astype(int)

    # Build graph
    print(f"  Applying cosine threshold >= {COSINE_THRESHOLD}...")
    G = nx.Graph()

    for i, sub in enumerate(submolts):
        G.add_node(sub, author_count=submolt_totals[sub])

    for i in range(n_submolts):
        for j in range(i + 1, n_submolts):
            sim = float(sim_matrix[i, j])
            if sim >= COSINE_THRESHOLD:
                G.add_edge(
                    submolts[i], submolts[j],
                    weight=sim,
                    shared_agents=int(cooccurrence[i, j]),
                )

    print(f"  Nodes: {G.number_of_nodes()}")
    print(f"  Edges: {G.number_of_edges()}")

    finalize_layer(G, "temporal_overlap", OUTPUT_PATH, count_label="Posts")


if __name__ == "__main__":
    main()
