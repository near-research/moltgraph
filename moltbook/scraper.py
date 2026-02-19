"""Moltbook API scraper with rate limiting, caching, and interaction extraction."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests


class MoltbookScraper:
    """Scrapes posts and comments from the Moltbook API and produces interaction dicts."""

    BASE_URL = "https://www.moltbook.com/api/v1"
    REQUEST_DELAY = 0.65  # seconds between requests to stay under 100 req/min

    def __init__(self, api_key: str) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        })
        self._posts_cache: dict[str, dict] = {}
        self._comments_cache: dict[str, list[dict]] = {}
        self._agents_cache: dict[str, dict] = {}

    MAX_RETRIES = 5

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """Rate-limit-aware GET request. Sleeps proactively + handles 429s."""
        url = f"{self.BASE_URL}{path}"
        time.sleep(self.REQUEST_DELAY)
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = self._session.get(url, params=params, timeout=30)
            except requests.ConnectionError:
                wait = 2 ** attempt * 5
                print(f"  Connection error — retrying in {wait}s (attempt {attempt + 1}/{self.MAX_RETRIES})")
                time.sleep(wait)
                continue
            if resp.status_code == 429:
                body = resp.json()
                wait = float(body.get("retry_after_seconds", body.get("retry_after_minutes", 1) * 60))
                print(f"  Rate limited — waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise requests.ConnectionError(f"Failed after {self.MAX_RETRIES} retries: {url}")

    def _cache_agent(self, agent: dict | str | None) -> str | None:
        """Cache an agent object and return its name."""
        if agent is None:
            return None
        if isinstance(agent, str):
            return agent
        name = agent.get("name")
        if name and name not in self._agents_cache:
            self._agents_cache[name] = agent
        return name

    def _fetch_all_submolts(self) -> list[dict]:
        """Paginate through the submolts listing endpoint."""
        all_submolts: list[dict] = []
        offset = 0
        limit = 100

        while True:
            data = self._get("/submolts", {"limit": limit, "offset": offset})
            batch = data.get("submolts", [])
            if not batch:
                break
            all_submolts.extend(batch)
            if len(batch) < limit:
                break
            offset += limit

        return all_submolts

    def scrape_by_submolt(
        self,
        names: list[str] | None = None,
        progress_path: str | None = None,
    ) -> list[dict]:
        """Fetch submolts, then scrape posts + comments from each.

        Args:
            names: If provided, only scrape these submolt names. Otherwise fetch all.
            progress_path: If provided, save progress after each submolt and skip
                already-scraped submolts on resume.
        """
        if names:
            submolts = [{"name": n} for n in names]
            print(f"Targeting {len(submolts)} submolt(s)")
        else:
            print("Fetching submolt list...")
            submolts = self._fetch_all_submolts()
            print(f"Found {len(submolts)} submolts")

        all_interactions: list[dict] = []
        done_submolts: set[str] = set()

        # Resume from progress file
        if progress_path:
            p = Path(progress_path)
            if p.exists():
                existing = json.loads(p.read_text())
                all_interactions = existing.get("interactions", [])
                done_submolts = set(existing.get("scraped_submolts", []))
                # Restore agent cache
                for name, agent in existing.get("agents", {}).items():
                    if name not in self._agents_cache:
                        self._agents_cache[name] = agent
                print(f"Resuming: {len(all_interactions)} interactions from {len(done_submolts)} submolts")

        for i, submolt in enumerate(submolts):
            name = submolt.get("name", "")
            if name in done_submolts:
                continue

            print(f"\n[{i + 1}/{len(submolts)}] Scraping submolt: {name}")

            posts = self._fetch_posts_for_submolt(name)
            print(f"  {len(posts)} posts")

            posts_with_comments = [p for p in posts if p.get("comment_count", 0) > 0]
            if len(posts_with_comments) < len(posts):
                print(f"  {len(posts_with_comments)}/{len(posts)} have comments — skipping {len(posts) - len(posts_with_comments)} empty")

            for post in posts_with_comments:
                interactions = self._scrape_post(post, name)
                all_interactions.extend(interactions)

            done_submolts.add(name)
            print(f"  Total interactions so far: {len(all_interactions)}")

            # Save progress incrementally
            if progress_path:
                output = {
                    "interactions": all_interactions,
                    "agents": self.get_cached_agents(),
                    "scraped_submolts": sorted(done_submolts),
                }
                Path(progress_path).write_text(json.dumps(output, indent=2, default=str))

        return all_interactions

    def scrape_post_ids(self, ids: list[str]) -> list[dict]:
        """Scrape specific posts by ID."""
        all_interactions: list[dict] = []

        for post_id in ids:
            print(f"Fetching post {post_id}...")
            try:
                data = self._get(f"/posts/{post_id}")
                post = data if "id" in data else data.get("post", data)
                submolt = post.get("submolt", {})
                submolt_name = submolt.get("name", "") if isinstance(submolt, dict) else str(submolt)
                interactions = self._scrape_post(post, submolt_name)
                all_interactions.extend(interactions)
            except requests.HTTPError as e:
                print(f"  Error fetching post {post_id}: {e}")

        return all_interactions

    MAX_PAGES = 10000  # effectively unlimited

    def _fetch_posts_for_submolt(self, submolt_name: str) -> list[dict]:
        """Fetch all posts for a submolt using page-based pagination."""
        posts: list[dict] = []
        seen_ids: set[str] = set()
        page = 1
        limit = 100

        while page <= self.MAX_PAGES:
            params: dict[str, Any] = {
                "submolt": submolt_name,
                "sort": "new",
                "limit": limit,
                "page": page,
            }
            try:
                data = self._get("/posts", params=params)
            except requests.HTTPError:
                break

            batch = data.get("posts", [])
            if not batch:
                break

            for p in batch:
                pid = p.get("id")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    posts.append(p)
                    self._posts_cache[pid] = p
                    self._cache_agent(p.get("author") or p.get("created_by"))

            if not data.get("has_more", False):
                break

            page += 1

        if page > self.MAX_PAGES:
            print(f"  Warning: hit pagination cap ({self.MAX_PAGES} pages) for submolt '{submolt_name}'")

        return posts

    def _scrape_post(self, post: dict, submolt_name: str) -> list[dict]:
        """Fetch comments for a post and extract interactions."""
        post_id = post.get("id", "")
        post_author = self._cache_agent(post.get("author") or post.get("created_by"))

        if post_id in self._comments_cache:
            comments = self._comments_cache[post_id]
        else:
            try:
                data = self._get(f"/posts/{post_id}/comments", {"sort": "top"})
                comments = data.get("comments", [])
                if isinstance(data, list):
                    comments = data
            except requests.HTTPError:
                comments = []
            self._comments_cache[post_id] = comments

        return self._interactions_from_post(post_id, post_author, comments, submolt_name)

    def _interactions_from_post(
        self,
        post_id: str,
        post_author: str | None,
        comments: list[dict],
        submolt_name: str,
    ) -> list[dict]:
        """Convert post + comments into interaction dicts with target_agent resolved."""
        comment_author_map: dict[str, str] = {}
        for c in comments:
            cid = c.get("id", "")
            author = self._cache_agent(c.get("author") or c.get("created_by"))
            if cid and author:
                comment_author_map[cid] = author

        interactions: list[dict] = []

        for c in comments:
            commenter = self._cache_agent(c.get("author") or c.get("created_by"))
            if not commenter:
                print(f"  Warning: skipping comment {c.get('id')} in post {post_id} — no author")
                continue

            comment_id = c.get("id")
            parent_id = c.get("parent_id")
            timestamp = c.get("created_at", "")
            upvotes = c.get("upvotes", 0)

            if parent_id and parent_id in comment_author_map:
                target = comment_author_map[parent_id]
                if target != commenter:
                    interactions.append({
                        "action": "reply",
                        "agent": commenter,
                        "target_agent": target,
                        "post_id": post_id,
                        "comment_id": comment_id,
                        "parent_comment_id": parent_id,
                        "timestamp": timestamp,
                        "upvotes": upvotes,
                        "submolt": submolt_name,
                    })
            elif post_author and post_author != commenter:
                interactions.append({
                    "action": "comment",
                    "agent": commenter,
                    "target_agent": post_author,
                    "post_id": post_id,
                    "comment_id": comment_id,
                    "parent_comment_id": None,
                    "timestamp": timestamp,
                    "upvotes": upvotes,
                    "submolt": submolt_name,
                })

        return interactions

    def scrape_follows(
        self,
        agent_names: list[str] | None = None,
        max_agents: int = 500,
        skip_agents: set[str] | None = None,
        checkpoint_fn: "Callable[[list[dict]], None] | None" = None,
        checkpoint_every: int = 50,
    ) -> list[dict]:
        """Scrape follow relationships by fetching each agent's /following list.

        Args:
            agent_names: Specific agents to scrape. If None, enumerates agents
                from submolt posts and sorts by follower_count descending.
            max_agents: Maximum number of agents to scrape (default 500).
            checkpoint_fn: Called every checkpoint_every agents with current edges.
            checkpoint_every: Save checkpoint every N agents (default 50).
        """
        if agent_names:
            names = agent_names[:max_agents]
            print(f"Scraping follows for {len(names)} specified agent(s)")
        else:
            names = self._enumerate_agents(max_agents)

        if skip_agents:
            before = len(names)
            names = [n for n in names if n not in skip_agents]
            print(f"Resuming: skipping {before - len(names)} already-scraped agents, {len(names)} remaining")

        all_follows: list[dict] = []
        seen: set[tuple[str, str]] = set()

        for i, name in enumerate(names):
            print(f"[{i + 1}/{len(names)}] Fetching following for: {name}")
            page_following: list[dict] = []
            offset = 0
            limit = 100

            while True:
                try:
                    data = self._get(
                        f"/agents/{name}/following",
                        {"limit": limit, "offset": offset},
                    )
                except requests.HTTPError as e:
                    print(f"  Error: {e}")
                    break

                batch = data.get("following", [])
                if not batch:
                    break
                page_following.extend(batch)

                total = int(data.get("total", 0))
                if len(page_following) >= total or len(batch) < limit:
                    break
                offset += limit

            for agent in page_following:
                followed_name = self._cache_agent(agent)
                if followed_name and (name, followed_name) not in seen:
                    seen.add((name, followed_name))
                    all_follows.append({
                        "follower": name,
                        "following": followed_name,
                    })

            print(f"  {len(page_following)} following")

            if checkpoint_fn and (i + 1) % checkpoint_every == 0:
                checkpoint_fn(all_follows)
                print(f"  [checkpoint: {len(all_follows)} edges from {i + 1}/{len(names)} agents]")

        print(f"\nTotal follow edges: {len(all_follows)}")
        return all_follows

    def _enumerate_agents(self, max_agents: int) -> list[str]:
        """Enumerate agents from submolt posts, sorted by follower_count desc."""
        print("Enumerating agents from submolt posts...")
        submolts = self._fetch_all_submolts()
        print(f"Found {len(submolts)} submolts, fetching posts to discover agents...")

        for i, submolt in enumerate(submolts):
            name = submolt.get("name", "")
            posts = self._fetch_posts_for_submolt(name)
            if (i + 1) % 10 == 0:
                print(f"  Scanned {i + 1}/{len(submolts)} submolts, {len(self._agents_cache)} agents found")

        # Sort by follower_count descending, prioritizing high-follower agents
        agents = sorted(
            self._agents_cache.values(),
            key=lambda a: a.get("followerCount", a.get("follower_count", 0)),
            reverse=True,
        )
        names = [a["name"] for a in agents if a.get("name")][:max_agents]
        print(f"Selected top {len(names)} agents by follower count")
        return names

    def save_follows(self, follows: list[dict], path: str) -> None:
        """Save follow relationships + cached agents to JSON."""
        output = {
            "follows": follows,
            "agents": self.get_cached_agents(),
        }
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(output, indent=2, default=str))
        print(f"Saved {len(follows)} follow edges to {out_path}")

    def get_cached_agents(self) -> dict[str, dict]:
        """Return all cached agent profiles."""
        return dict(self._agents_cache)

    def save(self, interactions: list[dict], path: str) -> None:
        """Save interactions + cached agents to JSON."""
        output = {
            "interactions": interactions,
            "agents": self.get_cached_agents(),
        }
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(output, indent=2, default=str))
        print(f"Saved {len(interactions)} interactions to {out_path}")
