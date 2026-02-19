"""Fetch all submolts from Moltbook API with pagination and list by member count."""

from __future__ import annotations

import json
from pathlib import Path

import requests

from overlap.api import create_session, rate_limited_get

OUTPUT_PATH = "data/submolts.json"


def fetch_all_submolts(session: requests.Session) -> list[dict]:
    """Paginate through all submolts using the page= parameter."""
    all_submolts: list[dict] = []
    page = 1

    while True:
        print(f"Fetching page {page}...")
        data = rate_limited_get(session, "/submolts", params={"page": page, "limit": 100})
        batch = data.get("submolts", [])
        if not batch:
            break
        all_submolts.extend(batch)
        print(f"  Got {len(batch)} submolts (total: {len(all_submolts)})")
        if len(batch) < 100:
            break
        page += 1

    return all_submolts


def main() -> None:
    session = create_session()

    print("Fetching all submolts...\n")
    raw = fetch_all_submolts(session)
    seen, submolts = set(), []
    for s in raw:
        sid = s.get("id")
        if sid not in seen:
            seen.add(sid)
            submolts.append(s)
    print(f"\nTotal fetched: {len(raw)}, unique: {len(submolts)} ({len(raw) - len(submolts)} duplicates removed)")

    # Save full metadata
    out_path = Path(OUTPUT_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(submolts, indent=2, default=str))
    print(f"Saved to {out_path}\n")

    # Sort by subscriber_count descending and print
    sorted_submolts = sorted(submolts, key=lambda s: s.get("subscriber_count", 0), reverse=True)

    print(f"{'Rank':<6}{'Submolt':<30}{'Subscribers':>12}{'Posts':>10}")
    print("-" * 58)
    for i, s in enumerate(sorted_submolts, 1):
        name = s.get("name", "unknown")
        subs = s.get("subscriber_count", 0)
        posts = s.get("post_count", 0)
        print(f"{i:<6}{name:<30}{subs:>12}{posts:>10}")


if __name__ == "__main__":
    main()
