"""Fetch unique post authors per submolt for bipartite membership analysis.

Paginates through all posts for each active submolt, extracts author IDs,
and saves incrementally to data/membership.json.

Skips: general, mbc20, mbc-20, mbc20-mint (noise/spam).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from overlap.api import create_session, rate_limited_get, REQUEST_DELAY

OUTPUT_PATH = "data/membership.json"
SUBMOLTS_PATH = "data/submolts.json"
SKIP = {"general", "mbc20", "mbc-20", "mbc20-mint"}
MAX_PAGES = 50  # cap per submolt (5000 posts max)


def fetch_authors_for_submolt(session: requests.Session, name: str) -> set[str]:
    """Paginate through all posts in a submolt and return unique author names."""
    authors: set[str] = set()
    page = 1

    while page <= MAX_PAGES:
        try:
            data = rate_limited_get(
                session, "/posts",
                params={"submolt": name, "sort": "new", "limit": 100, "page": page},
            )
        except requests.HTTPError:
            break

        batch = data.get("posts", [])
        if not batch:
            break

        for post in batch:
            author = post.get("author") or post.get("created_by")
            if isinstance(author, dict):
                name_or_id = author.get("name") or author.get("id")
            elif isinstance(author, str):
                name_or_id = author
            else:
                continue
            if name_or_id:
                authors.add(name_or_id)

        if len(batch) < 100:
            break
        page += 1

    return authors


def load_progress() -> dict[str, list[str]]:
    """Load existing membership data if resuming."""
    path = Path(OUTPUT_PATH)
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_progress(membership: dict[str, list[str]]) -> None:
    """Save membership data incrementally."""
    path = Path(OUTPUT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(membership, indent=2, default=str))


def main() -> None:
    # Load submolt list
    submolts_data = json.loads(Path(SUBMOLTS_PATH).read_text())
    seen = set()
    unique = []
    for s in submolts_data:
        sid = s.get("id")
        if sid not in seen:
            seen.add(sid)
            unique.append(s)

    # Filter to active, non-spam submolts
    active = [s for s in unique if s.get("post_count", 0) >= 1 and s.get("name") not in SKIP]
    active.sort(key=lambda s: s.get("post_count", 0), reverse=True)

    print(f"Active submolts to process: {len(active)}")
    total_pages_est = sum(min(MAX_PAGES, max(1, (s.get("post_count", 0) + 99) // 100)) for s in active)
    print(f"Estimated API calls: ~{total_pages_est:,}")
    print(f"Estimated time: ~{total_pages_est * REQUEST_DELAY / 60:.0f} min\n")

    session = create_session()

    # Resume from previous run if available
    membership = load_progress()
    already_done = set(membership.keys())
    if already_done:
        print(f"Resuming — {len(already_done)} submolts already fetched\n")

    save_every = 5  # save progress every N submolts
    processed = 0
    t_start = time.time()

    for i, submolt in enumerate(active):
        name = submolt.get("name", "")
        if name in already_done:
            continue

        post_count = submolt.get("post_count", 0)
        elapsed = time.time() - t_start
        rate = processed / elapsed if elapsed > 0 else 0
        remaining = len(active) - i
        eta_min = remaining / rate / 60 if rate > 0 else 0

        print(f"[{i + 1}/{len(active)}] {name} ({post_count} posts) — ETA {eta_min:.0f}m")

        authors = fetch_authors_for_submolt(session, name)
        membership[name] = sorted(authors)
        processed += 1

        print(f"  -> {len(authors)} unique authors")

        if processed % save_every == 0:
            save_progress(membership)
            print(f"  [checkpoint saved: {len(membership)} submolts]\n")

    # Final save
    save_progress(membership)

    total_authors = set()
    for authors in membership.values():
        total_authors.update(authors)

    elapsed = time.time() - t_start
    print(f"\nDone. {len(membership)} submolts, {len(total_authors)} unique agents.")
    print(f"Time: {elapsed / 60:.1f} min")
    print(f"Saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
