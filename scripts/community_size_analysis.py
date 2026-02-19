#!/usr/bin/env python3
"""Analyze community size distribution from post_overlap layer."""

import json
from collections import defaultdict, Counter
from pathlib import Path

DATA_PATH = str(Path(__file__).resolve().parent.parent / "data" / "overlap_graphs.json")

def main():
    # Load data
    print("Loading overlap_graphs.json...")
    with open(DATA_PATH) as f:
        data = json.load(f)

    nodes = data["post_overlap"]["nodes"]
    print(f"Total submolts (nodes): {len(nodes)}")

    # Group by community
    communities = defaultdict(list)
    for node in nodes:
        communities[node["community"]].append(node["id"])

    print(f"Total communities: {len(communities)}")
    print()

    # Compute sizes
    sizes = {cid: len(members) for cid, members in communities.items()}
    size_values = sorted(sizes.values(), reverse=True)

    # ── Full distribution ──────────────────────────────────────────────
    print("=" * 70)
    print("FULL COMMUNITY SIZE DISTRIBUTION")
    print("=" * 70)
    size_counts = Counter(size_values)
    print(f"{'Size':<8} {'Count':<8} {'Cumulative submolts'}")
    print("-" * 40)
    cumulative = 0
    for size in sorted(size_counts.keys()):
        count = size_counts[size]
        cumulative += size * count
        print(f"{size:<8} {count:<8} {cumulative}")

    # ── Range breakdown ────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("RANGE BREAKDOWN")
    print("=" * 70)

    ranges = [
        ("Size 1 (singletons)", lambda s: s == 1),
        ("Size 2-6 (below lower bound of 7)", lambda s: 2 <= s <= 6),
        ("Size 1-6 (total excluded by lower bound)", lambda s: 1 <= s <= 6),
        ("Size 7-200 (current 'valid' range)", lambda s: 7 <= s <= 200),
        ("Size 201-867 (between upper bound and mega-cluster)", lambda s: 201 <= s <= 867),
        ("Size 868+ (mega-cluster)", lambda s: s >= 868),
    ]

    for label, predicate in ranges:
        matching = [(cid, sz) for cid, sz in sizes.items() if predicate(sz)]
        total_submolts = sum(sz for _, sz in matching)
        print(f"\n{label}:")
        print(f"  Communities: {len(matching)}")
        print(f"  Total submolts: {total_submolts}")
        if matching:
            match_sizes = sorted([sz for _, sz in matching], reverse=True)
            print(f"  Size range: {min(match_sizes)} - {max(match_sizes)}")
            if len(match_sizes) <= 20:
                print(f"  Sizes: {match_sizes}")

    # ── Communities with 2-6 members: top 10 largest ───────────────────
    print()
    print("=" * 70)
    print("TOP 10 LARGEST COMMUNITIES WITH 2-6 MEMBERS")
    print("(Checking for topical coherence)")
    print("=" * 70)

    small_communities = [(cid, members) for cid, members in communities.items()
                         if 2 <= len(members) <= 6]
    small_communities.sort(key=lambda x: len(x[1]), reverse=True)

    for i, (cid, members) in enumerate(small_communities[:10]):
        print(f"\n  Community {cid} (size {len(members)}):")
        for m in sorted(members):
            print(f"    - {m}")

    # Also show a few more to get a sense
    print(f"\n  ... and {len(small_communities) - 10} more communities in this range")

    # ── Communities with 201-400 members ───────────────────────────────
    print()
    print("=" * 70)
    print("COMMUNITIES WITH 201-400 MEMBERS")
    print("(Potential candidates for inclusion)")
    print("=" * 70)

    mid_large = [(cid, len(members)) for cid, members in communities.items()
                 if 201 <= len(members) <= 400]
    mid_large.sort(key=lambda x: x[1], reverse=True)

    if mid_large:
        for cid, sz in mid_large:
            # Show a few member names for context
            sample = sorted(communities[cid])[:8]
            sample_str = ", ".join(sample)
            if len(communities[cid]) > 8:
                sample_str += ", ..."
            print(f"\n  Community {cid} (size {sz}):")
            print(f"    Sample members: {sample_str}")
    else:
        print("  None found.")

    # ── Communities with 201-867 members ───────────────────────────────
    print()
    print("=" * 70)
    print("ALL COMMUNITIES WITH 201-867 MEMBERS (full list with sizes)")
    print("=" * 70)

    upper_range = [(cid, len(members)) for cid, members in communities.items()
                   if 201 <= len(members) <= 867]
    upper_range.sort(key=lambda x: x[1], reverse=True)

    if upper_range:
        for cid, sz in upper_range:
            sample = sorted(communities[cid])[:5]
            sample_str = ", ".join(sample)
            if len(communities[cid]) > 5:
                sample_str += ", ..."
            print(f"  Community {cid}: {sz} members  (e.g. {sample_str})")
    else:
        print("  None found.")

    # ── Summary statistics ─────────────────────────────────────────────
    print()
    print("=" * 70)
    print("SUMMARY STATISTICS")
    print("=" * 70)
    print(f"  Total communities: {len(communities)}")
    print(f"  Total submolts: {len(nodes)}")
    print(f"  Median community size: {sorted(size_values)[len(size_values)//2]}")
    print(f"  Mean community size: {sum(size_values)/len(size_values):.1f}")
    print(f"  Max community size: {max(size_values)}")
    print(f"  Min community size: {min(size_values)}")

    # Percentile breakdown (pure python)
    sorted_sizes = sorted(size_values)
    n = len(sorted_sizes)
    for p in [10, 25, 50, 75, 90, 95, 99]:
        idx = int(p / 100 * (n - 1))
        print(f"  {p}th percentile: {sorted_sizes[idx]}")


if __name__ == "__main__":
    main()
