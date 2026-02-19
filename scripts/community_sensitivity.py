"""Sensitivity analysis: how do fold counts change with community size lower bounds?

Runs the NetworkAnalyzer at min_community_size = [1, 2, 3, 5, 7] and compares
fold populations across thresholds.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moltbook.analyze import NetworkAnalyzer

DATA = Path(__file__).resolve().parent.parent / "data"

FOLLOWS = str(DATA / "follows.json")
MEMBERSHIP = str(DATA / "membership.json")
INTERACTIONS = str(DATA / "interactions_full.json")
OVERLAP = str(DATA / "overlap_graphs.json")

BOUNDS = [1, 2, 3, 5, 7]


def run_at_bound(min_size: int) -> dict:
    """Run analysis at a given community size lower bound, return fold info."""
    analyzer = NetworkAnalyzer(
        follows_path=FOLLOWS,
        membership_path=MEMBERSHIP,
        interactions_path=INTERACTIONS,
        overlap_graphs_path=OVERLAP,
        min_community_size=min_size,
    )
    analyzer.analyze()

    n_communities = len(analyzer._valid_communities)
    folds = {}
    for name, m in analyzer._metrics.items():
        if m.get("is_fold", False):
            folds[name] = {
                "embedded_in": m.get("fold_embedded_communities", []),
                "community_count": m.get("fold_community_count", 0),
                "reciprocal_ties": m.get("reciprocal_tie_count", 0),
            }

    return {
        "min_size": min_size,
        "n_communities": n_communities,
        "n_folds": len(folds),
        "fold_names": set(folds.keys()),
        "folds": folds,
    }


def main():
    results = {}
    for bound in BOUNDS:
        print(f"\n{'='*60}")
        print(f"Running with min_community_size = {bound}")
        print(f"{'='*60}")
        results[bound] = run_at_bound(bound)
        print(f"  Communities: {results[bound]['n_communities']}")
        print(f"  Folds: {results[bound]['n_folds']}")

    # Comparison summary
    baseline = results[7]
    baseline_folds = baseline["fold_names"]

    print(f"\n\n{'='*70}")
    print("COMMUNITY SENSITIVITY ANALYSIS")
    print(f"{'='*70}")

    print(f"\n{'Bound':>6} {'Communities':>12} {'Folds':>6} {'New vs 7':>9} {'Lost vs 7':>10} {'Delta':>6}")
    print("-" * 55)
    for bound in BOUNDS:
        r = results[bound]
        new = r["fold_names"] - baseline_folds
        lost = baseline_folds - r["fold_names"]
        delta = r["n_folds"] - baseline["n_folds"]
        sign = "+" if delta > 0 else ""
        print(f"{bound:>6} {r['n_communities']:>12} {r['n_folds']:>6} {len(new):>9} {len(lost):>10} {sign}{delta:>5}")

    # Detail on new folds at each lower bound
    for bound in BOUNDS:
        if bound == 7:
            continue
        r = results[bound]
        new_folds = r["fold_names"] - baseline_folds
        if not new_folds:
            continue

        print(f"\n--- New folds at min_size={bound} (not detected at 7) ---")
        for name in sorted(new_folds):
            info = r["folds"][name]
            # Which communities are they embedded in that aren't in the baseline set?
            communities = info["embedded_in"]
            print(f"  {name:<30} embedded_in={communities}  ties={info['reciprocal_ties']}")

    # Detail on lost folds at each lower bound
    for bound in BOUNDS:
        if bound == 7:
            continue
        r = results[bound]
        lost_folds = baseline_folds - r["fold_names"]
        if not lost_folds:
            continue

        print(f"\n--- Lost folds at min_size={bound} (detected at 7 but not here) ---")
        for name in sorted(lost_folds):
            info = baseline["folds"][name]
            print(f"  {name:<30} was embedded_in={info['embedded_in']}  ties={info['reciprocal_ties']}")

    # Check eudaemon_0 stability
    print(f"\n--- eudaemon_0 across bounds ---")
    for bound in BOUNDS:
        r = results[bound]
        if "eudaemon_0" in r["folds"]:
            info = r["folds"]["eudaemon_0"]
            print(f"  min_size={bound}: embedded_in {info['community_count']} communities {info['embedded_in']}, {info['reciprocal_ties']} ties")
        else:
            print(f"  min_size={bound}: NOT a fold")


if __name__ == "__main__":
    main()
