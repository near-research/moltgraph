"""CLI entry point for the Moltbook network graph visualization tool."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

from moltbook import MoltbookScraper, GraphBuilder, FollowGraphBuilder, Visualizer, NetworkAnalyzer

load_dotenv()


def cmd_scrape(args: argparse.Namespace) -> str:
    """Scrape interactions from Moltbook API."""
    api_key = args.api_key or os.environ.get("MOLTBOOK_API_KEY")
    if not api_key:
        sys.exit("Error: No API key. Pass --api-key or set MOLTBOOK_API_KEY in .env")

    scraper = MoltbookScraper(api_key)

    if args.mode == "posts":
        if not args.ids:
            sys.exit("Error: --ids required when --mode=posts")
        post_ids = [i.strip() for i in args.ids.split(",")]
        interactions = scraper.scrape_post_ids(post_ids)
    else:
        submolt_names = None
        if getattr(args, "submolts_file", None):
            submolt_names = json.loads(Path(args.submolts_file).read_text())
            print(f"Loaded {len(submolt_names)} submolts from {args.submolts_file}")
        elif args.submolts:
            submolt_names = [s.strip() for s in args.submolts.split(",")]

        progress_path = args.out if getattr(args, "resume", False) else None
        interactions = scraper.scrape_by_submolt(
            names=submolt_names,
            progress_path=progress_path,
        )

    scraper.save(interactions, args.out)
    return args.out


def cmd_import_db(args: argparse.Namespace) -> str:
    """Import interactions from Observatory SQLite database."""
    db_path = Path(args.db)
    if not db_path.exists():
        sys.exit(f"Error: database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Extract interactions: comments→posts (for post author/submolt),
    # left join comments→comments (for parent comment author on replies)
    print("Querying interactions from database...")
    cursor = conn.execute("""
        SELECT
            c.id        AS comment_id,
            c.post_id,
            c.agent_name AS commenter,
            c.parent_id  AS parent_comment_id,
            c.score      AS upvotes,
            c.created_at AS timestamp,
            p.agent_name AS post_author,
            p.submolt,
            pc.agent_name AS parent_comment_author
        FROM comments c
        JOIN posts p ON c.post_id = p.id
        LEFT JOIN comments pc ON c.parent_id = pc.id
        WHERE c.agent_name IS NOT NULL AND c.agent_name != ''
    """)

    interactions: list[dict] = []
    skipped_self = 0

    for row in cursor:
        commenter = row["commenter"]
        parent_id = row["parent_comment_id"]
        parent_author = row["parent_comment_author"]
        post_author = row["post_author"]

        # Determine action type and target
        if parent_id and parent_author:
            action = "reply"
            target = parent_author
        elif post_author:
            action = "comment"
            target = post_author
        else:
            continue

        # Skip self-interactions
        if commenter == target:
            skipped_self += 1
            continue

        interactions.append({
            "action": action,
            "agent": commenter,
            "target_agent": target,
            "post_id": row["post_id"],
            "comment_id": row["comment_id"],
            "parent_comment_id": parent_id,
            "timestamp": row["timestamp"] or "",
            "upvotes": row["upvotes"] or 0,
            "submolt": row["submolt"] or "",
        })

    print(f"Extracted {len(interactions)} interactions (skipped {skipped_self} self-interactions)")

    # Extract agent profiles
    print("Loading agent profiles...")
    agent_rows = conn.execute("""
        SELECT name, karma, follower_count, following_count, is_claimed
        FROM agents
        WHERE name IS NOT NULL AND name != ''
    """)
    agents: dict[str, dict] = {}
    for row in agent_rows:
        agents[row["name"]] = {
            "name": row["name"],
            "karma": row["karma"] or 0,
            "follower_count": row["follower_count"] or 0,
            "following_count": row["following_count"] or 0,
            "is_claimed": bool(row["is_claimed"]),
        }
    print(f"Loaded {len(agents)} agent profiles")

    conn.close()

    # Count action types
    replies = sum(1 for i in interactions if i["action"] == "reply")
    comments = len(interactions) - replies
    print(f"  {comments} comments on posts, {replies} replies to comments")

    # Save output
    output = {"interactions": interactions, "agents": agents}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"Saved to {out_path}")
    return args.out


def cmd_build(args: argparse.Namespace) -> str:
    """Build graph JSON from scraped interaction data."""
    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"Error: input file not found: {input_path}")
    raw = json.loads(input_path.read_text())
    interactions = raw.get("interactions", raw if isinstance(raw, list) else [])
    agents = raw.get("agents", {})

    builder = GraphBuilder(interactions, agents)
    builder.build()
    builder.save_json(args.out)
    return args.out


def cmd_viz(args: argparse.Namespace) -> str:
    """Generate HTML visualization from graph JSON."""
    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"Error: input file not found: {input_path}")
    graph_data = json.loads(input_path.read_text())
    viz = Visualizer(graph_data)
    viz.render(args.out)
    return args.out


def cmd_scrape_follows(args: argparse.Namespace) -> str:
    """Scrape follow relationships from Moltbook API."""
    api_key = args.api_key or os.environ.get("MOLTBOOK_API_KEY")
    if not api_key:
        sys.exit("Error: No API key. Pass --api-key or set MOLTBOOK_API_KEY in .env")

    scraper = MoltbookScraper(api_key)

    # Load agent names from file or comma-separated arg
    agent_names = None
    if getattr(args, "agents_file", None):
        agent_names = json.loads(Path(args.agents_file).read_text())
        print(f"Loaded {len(agent_names)} agents from {args.agents_file}")
    elif args.agents:
        agent_names = [a.strip() for a in args.agents.split(",")]

    # Resume support: load existing follows and skip already-scraped agents
    skip_agents: set[str] | None = None
    existing_follows: list[dict] = []
    existing_agents: dict[str, dict] = {}
    if getattr(args, "resume", False) and Path(args.out).exists():
        existing = json.loads(Path(args.out).read_text())
        existing_follows = existing.get("follows", [])
        existing_agents = existing.get("agents", {})
        skip_agents = {e["follower"] for e in existing_follows}
        print(f"Resuming: {len(existing_follows)} existing edges from {len(skip_agents)} agents")

    def checkpoint(new_follows: list[dict]) -> None:
        """Save progress incrementally during long scrapes."""
        if existing_follows:
            seen = {(e["follower"], e["following"]) for e in existing_follows}
            merged = list(existing_follows)
            for f in new_follows:
                if (f["follower"], f["following"]) not in seen:
                    merged.append(f)
        else:
            merged = new_follows
        merged_agents = {**existing_agents, **scraper.get_cached_agents()}
        output = {"follows": merged, "agents": merged_agents}
        Path(args.out).write_text(json.dumps(output, indent=2, default=str))

    follows = scraper.scrape_follows(
        agent_names=agent_names,
        max_agents=args.max_agents,
        skip_agents=skip_agents,
        checkpoint_fn=checkpoint,
    )

    # Final merge with existing data if resuming
    if existing_follows:
        seen = {(e["follower"], e["following"]) for e in existing_follows}
        for f in follows:
            if (f["follower"], f["following"]) not in seen:
                existing_follows.append(f)
        follows = existing_follows
        merged_agents = {**existing_agents, **scraper.get_cached_agents()}
        scraper._agents_cache = merged_agents

    scraper.save_follows(follows, args.out)
    return args.out


def cmd_build_follows(args: argparse.Namespace) -> str:
    """Build follow graph JSON from scraped follow data."""
    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"Error: input file not found: {input_path}")
    raw = json.loads(input_path.read_text())
    follows = raw.get("follows", [])
    agents = raw.get("agents", {})

    builder = FollowGraphBuilder(follows, agents)
    builder.build()
    builder.save_json(args.out)
    return args.out


def cmd_run_follows(args: argparse.Namespace) -> None:
    """Run the full follow pipeline: scrape-follows -> build-follows -> viz."""
    out_dir = Path(args.out_dir)
    follows_path = str(out_dir / "follows.json")
    graph_path = str(out_dir / "follow_graph.json")
    viz_path = str(out_dir / "follows.html")

    # Scrape follows
    scrape_ns = argparse.Namespace(
        api_key=args.api_key,
        agents=args.agents,
        agents_file=None,
        max_agents=args.max_agents,
        resume=False,
        out=follows_path,
    )
    cmd_scrape_follows(scrape_ns)

    # Build follow graph
    build_ns = argparse.Namespace(input=follows_path, out=graph_path)
    cmd_build_follows(build_ns)

    # Visualize
    viz_ns = argparse.Namespace(input=graph_path, out=viz_path)
    cmd_viz(viz_ns)

    print(f"\nFollow pipeline complete! Open {viz_path} in your browser.")


def cmd_analyze(args: argparse.Namespace) -> None:
    """Cross-reference membership and follow data to identify structural roles."""
    if not Path(args.follows).exists():
        sys.exit(f"Error: follows file not found: {args.follows}")

    membership_path = args.membership if args.membership and Path(args.membership).exists() else None
    interactions_path = args.interactions if args.interactions and Path(args.interactions).exists() else None

    if not membership_path and not interactions_path:
        print("Warning: no membership or interaction data provided — submolt breadth will be empty")

    overlap_path = args.overlap_graphs if args.overlap_graphs and Path(args.overlap_graphs).exists() else None

    analyzer = NetworkAnalyzer(
        follows_path=args.follows,
        membership_path=membership_path,
        interactions_path=interactions_path,
        overlap_graphs_path=overlap_path,
        min_community_size=args.min_community_size,
    )
    analyzer.analyze()
    print(analyzer.report())

    if args.out:
        analyzer.save_json(args.out)


def cmd_run(args: argparse.Namespace) -> None:
    """Run the full pipeline: scrape -> build -> viz."""
    out_dir = Path(args.out_dir)
    interactions_path = str(out_dir / "interactions.json")
    graph_path = str(out_dir / "graph.json")
    viz_path = str(out_dir / "index.html")

    # Scrape
    scrape_ns = argparse.Namespace(
        api_key=args.api_key,
        mode=args.mode,
        ids=args.ids,
        submolts=args.submolts,
        submolts_file=None,
        resume=False,
        out=interactions_path,
    )
    cmd_scrape(scrape_ns)

    # Build
    build_ns = argparse.Namespace(input=interactions_path, out=graph_path)
    cmd_build(build_ns)

    # Viz
    viz_ns = argparse.Namespace(input=graph_path, out=viz_path)
    cmd_viz(viz_ns)

    print(f"\nPipeline complete! Open {viz_path} in your browser.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Moltbook network graph visualization tool",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scrape
    p_scrape = sub.add_parser("scrape", help="Fetch data from Moltbook API")
    p_scrape.add_argument("--api-key", help="Moltbook API key (or set MOLTBOOK_API_KEY)")
    p_scrape.add_argument("--mode", choices=["submolts", "posts"], default="submolts",
                          help="Scraping strategy (default: submolts)")
    p_scrape.add_argument("--ids", help="Comma-separated post IDs (required for --mode=posts)")
    p_scrape.add_argument("--submolts", help="Comma-separated submolt names to target (default: all)")
    p_scrape.add_argument("--submolts-file", help="JSON file with list of submolt names to scrape")
    p_scrape.add_argument("--resume", action="store_true", help="Resume: skip already-scraped submolts, save progress incrementally")
    p_scrape.add_argument("--out", default="data/interactions.json", help="Output path")
    p_scrape.set_defaults(func=cmd_scrape)

    # import-db
    p_idb = sub.add_parser("import-db", help="Import interactions from Observatory SQLite DB")
    p_idb.add_argument("--db", default="data/observatory.db", help="Path to Observatory SQLite database")
    p_idb.add_argument("--out", default="data/interactions_full.json", help="Output interactions JSON")
    p_idb.set_defaults(func=cmd_import_db)

    # build
    p_build = sub.add_parser("build", help="Build graph from scraped interactions")
    p_build.add_argument("--input", default="data/interactions.json", help="Input interactions JSON")
    p_build.add_argument("--out", default="data/graph.json", help="Output graph JSON")
    p_build.set_defaults(func=cmd_build)

    # viz
    p_viz = sub.add_parser("viz", help="Generate HTML visualization")
    p_viz.add_argument("--input", default="data/graph.json", help="Input graph JSON")
    p_viz.add_argument("--out", default="output/index.html", help="Output HTML path")
    p_viz.set_defaults(func=cmd_viz)

    # run (full pipeline)
    p_run = sub.add_parser("run", help="Full pipeline: scrape + build + viz")
    p_run.add_argument("--api-key", help="Moltbook API key (or set MOLTBOOK_API_KEY)")
    p_run.add_argument("--mode", choices=["submolts", "posts"], default="submolts")
    p_run.add_argument("--ids", help="Comma-separated post IDs (for --mode=posts)")
    p_run.add_argument("--submolts", help="Comma-separated submolt names to target (default: all)")
    p_run.add_argument("--out-dir", default="./output", help="Output directory")
    p_run.set_defaults(func=cmd_run)

    # analyze
    p_az = sub.add_parser("analyze", help="Cross-reference membership + follow data")
    p_az.add_argument("--follows", default="data/follows.json", help="Follows JSON")
    p_az.add_argument("--membership", default="data/membership.json", help="Membership JSON (submolt -> agents)")
    p_az.add_argument("--interactions", default=None, help="Optional interactions JSON for extra signal")
    p_az.add_argument("--overlap-graphs", default="data/overlap_graphs.json", help="Overlap graphs JSON for fold detection")
    p_az.add_argument("--min-community-size", type=int, default=7, help="Min submolt members for a valid community (default: 7)")
    p_az.add_argument("--out", default="data/analysis.json", help="Output analysis JSON")
    p_az.set_defaults(func=cmd_analyze)

    # scrape-follows
    p_sf = sub.add_parser("scrape-follows", help="Scrape follow relationships from API")
    p_sf.add_argument("--api-key", help="Moltbook API key (or set MOLTBOOK_API_KEY)")
    p_sf.add_argument("--agents", help="Comma-separated agent names to scrape (default: enumerate from posts)")
    p_sf.add_argument("--agents-file", help="JSON file with list of agent names to scrape")
    p_sf.add_argument("--max-agents", type=int, default=500, help="Max agents to scrape (default: 500)")
    p_sf.add_argument("--resume", action="store_true", help="Resume: skip agents already in output file")
    p_sf.add_argument("--out", default="data/follows.json", help="Output path")
    p_sf.set_defaults(func=cmd_scrape_follows)

    # build-follows
    p_bf = sub.add_parser("build-follows", help="Build follow graph from scraped follow data")
    p_bf.add_argument("--input", default="data/follows.json", help="Input follows JSON")
    p_bf.add_argument("--out", default="data/follow_graph.json", help="Output graph JSON")
    p_bf.set_defaults(func=cmd_build_follows)

    # run-follows (full follow pipeline)
    p_rf = sub.add_parser("run-follows", help="Full follow pipeline: scrape + build + viz")
    p_rf.add_argument("--api-key", help="Moltbook API key (or set MOLTBOOK_API_KEY)")
    p_rf.add_argument("--agents", help="Comma-separated agent names to scrape")
    p_rf.add_argument("--max-agents", type=int, default=500, help="Max agents to scrape (default: 500)")
    p_rf.add_argument("--out-dir", default="./output", help="Output directory")
    p_rf.set_defaults(func=cmd_run_follows)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
