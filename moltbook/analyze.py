"""Cross-reference interaction and follow data to identify structural roles in the network."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


class NetworkAnalyzer:
    """Cross-references membership and follow datasets to classify agent roles."""

    def __init__(
        self,
        follows_path: str,
        membership_path: str | None = None,
        interactions_path: str | None = None,
        overlap_graphs_path: str | None = None,
        min_community_size: int = 7,
    ) -> None:
        self._min_community_size = min_community_size
        raw_fl = json.loads(Path(follows_path).read_text())
        self._follows = raw_fl.get("follows", [])

        # Agent profiles: load observatory (older) first, then API (newer) overwrites
        self._agents: dict[str, dict] = {}

        # Membership data: {submolt_name: [agent_name, ...]}
        self._membership: dict[str, list[str]] = {}
        if membership_path and Path(membership_path).exists():
            self._membership = json.loads(Path(membership_path).read_text())

        # Optional interaction data for additional signal
        self._interactions: list[dict] = []
        if interactions_path and Path(interactions_path).exists():
            raw_ix = json.loads(Path(interactions_path).read_text())
            self._interactions = raw_ix.get("interactions", [])
            self._agents.update(raw_ix.get("agents", {}))

        # Preserve observatory is_claimed before API merge (ground truth for bot/human)
        _obs_claimed = {
            name: a["is_claimed"]
            for name, a in self._agents.items()
            if "is_claimed" in a
        }

        # API-scraped follow data has most current profiles — load last to win
        self._agents.update(raw_fl.get("agents", {}))

        # Restore observatory is_claimed (API returns near-universal True, not reliable)
        for name, claimed in _obs_claimed.items():
            if name in self._agents:
                self._agents[name]["is_claimed"] = claimed

        # Overlap graph cluster assignments (submolt -> community)
        self._submolt_clusters: dict[str, int] = {}
        if overlap_graphs_path and Path(overlap_graphs_path).exists():
            og = json.loads(Path(overlap_graphs_path).read_text())
            # Use post_overlap layer — broadest coverage (~28 communities with 7+ members)
            layer = og.get("post_overlap", {})
            for node in layer.get("nodes", []):
                if "id" in node and "community" in node:
                    self._submolt_clusters[node["id"]] = node["community"]

        # Computed per-agent metrics
        self._metrics: dict[str, dict] = {}

        # Intermediate data built during analysis
        self._valid_communities: set[int] = set()
        self._reciprocal_ties: dict[str, set[str]] = defaultdict(set)
        self._mutual_ties: dict[str, set[str]] = defaultdict(set)
        self._edge_scores: dict[tuple[str, str], int] = defaultdict(int)
        self._bridging: dict = {}
        self._score_diagnostics: dict = {}
        self._temporal_folds: dict = {}

    def analyze(self) -> NetworkAnalyzer:
        """Run the full analysis pipeline. Returns self for chaining."""
        self._build_cluster_map()
        self._compute_submolt_breadth()
        self._compute_follow_metrics()
        self._compute_reciprocal_ties()
        self._detect_folds()
        self._compute_score_diagnostics()
        self._classify_roles()
        self._compute_bridging_topology()
        self._compute_temporal_folds()
        return self

    def _build_cluster_map(self) -> None:
        """Map agents to their primary posting community via membership + overlap clusters."""
        if not self._submolt_clusters:
            print("Warning: no overlap graph cluster data — fold detection, bridging, and temporal analysis will be skipped")
            return

        # Filter to cohesive communities: min_community_size+ submolt members, cap at 200
        # (the mega-community with 800+ submolts is a residual catch-all, not cohesive)
        comm_sizes = Counter(self._submolt_clusters.values())
        valid_comms = {c for c, n in comm_sizes.items() if self._min_community_size <= n <= 200}
        self._valid_communities = valid_comms

        # Map agents to clusters via membership data
        agent_submolt_counts: dict[str, Counter] = defaultdict(Counter)
        for submolt, members in self._membership.items():
            cluster = self._submolt_clusters.get(submolt)
            if cluster is None or cluster not in valid_comms:
                continue
            if not isinstance(members, list):
                continue
            for agent in members:
                if isinstance(agent, str) and agent:
                    agent_submolt_counts[agent][cluster] += 1

        # Also map via interaction data
        for ix in self._interactions:
            submolt = ix.get("submolt", "")
            cluster = self._submolt_clusters.get(submolt)
            if cluster is None or cluster not in valid_comms:
                continue
            for key in ("agent", "target_agent"):
                name = ix.get(key, "")
                if name:
                    agent_submolt_counts[name][cluster] += 1

        # Store primary community for each agent (most active cluster)
        for name, counts in agent_submolt_counts.items():
            m = self._metrics.setdefault(name, {})
            primary = counts.most_common(1)[0][0] if counts else -1
            m["primary_community"] = primary
            m["community_count"] = len(counts)

    def _compute_reciprocal_ties(self) -> None:
        """Identify reciprocal ties: mutual follows + bidirectional interactions."""
        # Mutual follows (already computed in _compute_follow_metrics)
        for name, m in self._metrics.items():
            mutuals = m.get("mutual_names", [])
            for partner in mutuals:
                self._mutual_ties[name].add(partner)
                self._reciprocal_ties[name].add(partner)

        # Reciprocal interactions: both A->B and B->A exist
        outgoing: dict[str, set[str]] = defaultdict(set)
        for ix in self._interactions:
            agent = ix.get("agent", "")
            target = ix.get("target_agent", "")
            if agent and target and agent != target:
                outgoing[agent].add(target)
                self._edge_scores[(agent, target)] += ix.get("upvotes", 0)

        for agent, targets in outgoing.items():
            for target in targets:
                if agent in outgoing.get(target, set()):
                    self._reciprocal_ties[agent].add(target)

    def _detect_folds(self) -> None:
        """Detect structural folds per Vedres & Stark: reciprocal ties embedded in 2+ cohesive groups.

        An agent is *embedded* in community X if they have 2+ interaction partners
        whose primary community is X. A fold agent is embedded in 2+ distinct communities.
        """
        if not self._submolt_clusters:
            return

        for agent, partners in self._reciprocal_ties.items():
            # Count partners per primary community
            partner_community_counts: Counter = Counter()
            for partner in partners:
                pm = self._metrics.get(partner, {})
                pc = pm.get("primary_community")
                if pc is not None and pc != -1:
                    partner_community_counts[pc] += 1

            # Embedded = 2+ partners in that community
            embedded_in = [c for c, n in partner_community_counts.items() if n >= 2]

            m = self._metrics.setdefault(agent, {})
            m["fold_embedded_communities"] = sorted(embedded_in)
            m["fold_community_count"] = len(embedded_in)
            m["reciprocal_tie_count"] = len(partners)
            m["mutual_tie_count"] = len(self._mutual_ties.get(agent, set()))

            # Score-weighted reciprocal tie strength
            score = 0
            scored_count = 0
            for p in partners:
                ab = self._edge_scores.get((agent, p), 0)
                ba = self._edge_scores.get((p, agent), 0)
                score += ab + ba
                if ab + ba > 0:
                    scored_count += 1
            m["reciprocal_tie_score"] = score
            m["scored_reciprocal_tie_count"] = scored_count
            m["score_efficiency"] = round(scored_count / len(partners), 4) if partners else 0.0

            # Fold requires 2+ embedded communities AND 5+ reciprocal ties
            # (fewer ties with high partner concentration is noise, not embeddedness)
            if len(embedded_in) >= 2 and len(partners) >= 5:
                m["is_fold"] = True
            else:
                m["is_fold"] = False

    def _compute_score_diagnostics(self) -> None:
        """Diagnostic: what if fold detection only counted reciprocal ties with non-zero scores?"""
        if not self._submolt_clusters:
            return

        original_folds = set()
        scored_folds = set()

        for agent, partners in self._reciprocal_ties.items():
            m = self._metrics.get(agent, {})
            if m.get("is_fold"):
                original_folds.add(agent)

            # Filter to scored partners (non-zero upvote exchange in either direction)
            scored_partners = set()
            for p in partners:
                if self._edge_scores.get((agent, p), 0) + self._edge_scores.get((p, agent), 0) > 0:
                    scored_partners.add(p)

            if len(scored_partners) < 5:
                continue

            # Re-run embeddedness check with scored partners only
            partner_community_counts: Counter = Counter()
            for p in scored_partners:
                pm = self._metrics.get(p, {})
                pc = pm.get("primary_community")
                if pc is not None and pc != -1:
                    partner_community_counts[pc] += 1

            embedded_in = [c for c, n in partner_community_counts.items() if n >= 2]
            if len(embedded_in) >= 2:
                scored_folds.add(agent)

        lost = original_folds - scored_folds
        gained = scored_folds - original_folds

        self._score_diagnostics = {
            "original_folds": len(original_folds),
            "scored_folds": len(scored_folds),
            "lost": sorted(lost),
            "gained": sorted(gained),
            "survival_rate": len(original_folds & scored_folds) / len(original_folds) if original_folds else 0.0,
        }

    def _compute_submolt_breadth(self) -> None:
        """Count how many distinct submolts each agent is a member of."""
        agent_submolts: dict[str, set[str]] = defaultdict(set)

        # Primary source: membership data (agent subscriptions per submolt)
        for submolt_name, members in self._membership.items():
            if not isinstance(members, list):
                continue
            for agent_name in members:
                if isinstance(agent_name, str) and agent_name:
                    agent_submolts[agent_name].add(submolt_name)

        # Supplemental: interaction data (if available)
        for ix in self._interactions:
            agent = ix.get("agent", "")
            target = ix.get("target_agent", "")
            submolt = ix.get("submolt", "")
            if not submolt:
                continue
            if agent:
                agent_submolts[agent].add(submolt)
            if target:
                agent_submolts[target].add(submolt)

        for name, submolts in agent_submolts.items():
            m = self._metrics.setdefault(name, {})
            m["submolt_count"] = len(submolts)
            m["submolts"] = sorted(submolts)

    def _compute_follow_metrics(self) -> None:
        """Compute follower/following counts and mutual follows from follow data."""
        following_map: dict[str, set[str]] = defaultdict(set)
        followers_map: dict[str, set[str]] = defaultdict(set)

        for f in self._follows:
            follower = f.get("follower", "")
            following = f.get("following", "")
            if follower and following:
                following_map[follower].add(following)
                followers_map[following].add(follower)

        all_agents = set(following_map.keys()) | set(followers_map.keys())
        for name in all_agents:
            m = self._metrics.setdefault(name, {})
            own_following = following_map.get(name, set())
            own_followers = followers_map.get(name, set())
            mutual = own_following & own_followers

            # Use API profile counts where available, fall back to scraped graph counts
            agent = self._agents.get(name, {})
            api_followers = agent.get("followerCount", agent.get("follower_count", 0))
            api_following = agent.get("followingCount", agent.get("following_count", 0))

            m["follower_count"] = api_followers if api_followers is not None else len(own_followers)
            m["following_count"] = api_following if api_following is not None else len(own_following)
            m["mutual_count"] = len(mutual)
            m["mutual_names"] = sorted(mutual)
            m["graph_followers"] = len(own_followers)
            m["graph_following"] = len(own_following)

            # Ratio: high = attractor (many followers, few following)
            # When following_count is 0, use follower_count as ratio (capped to avoid
            # confusing raw counts with computed ratios in downstream thresholds)
            if m["following_count"] > 0:
                m["follower_ratio"] = round(m["follower_count"] / m["following_count"], 2)
            else:
                m["follower_ratio"] = float(m["follower_count"]) if m["follower_count"] > 0 else 0.0

    def _classify_roles(self) -> None:
        """Classify each agent into structural roles based on their metrics."""
        # Count interactions, upvotes, and threading per agent
        ix_counts: Counter = Counter()
        ix_upvotes: Counter = Counter()
        reply_counts: Counter = Counter()
        for ix in self._interactions:
            agent = ix.get("agent", "")
            if agent:
                ix_counts[agent] += 1
                ix_upvotes[agent] += ix.get("upvotes", 0)
                if ix.get("action") == "reply":
                    reply_counts[agent] += 1

        for name, m in self._metrics.items():
            roles = []

            # Structural fold (Vedres & Stark): reciprocal ties embedded in 2+ cohesive groups
            is_fold = m.get("is_fold", False)
            if is_fold:
                roles.append("fold")

            # Flag automated folds: zero karma + high interaction volume
            # Only check agents with known profiles — missing agents default to
            # karma=0 which would falsely trigger automated classification
            agent_profile = self._agents.get(name)
            agent_karma = agent_profile.get("karma", 0) if agent_profile else None
            if is_fold and agent_karma == 0 and ix_counts.get(name, 0) >= 1000:
                m["fold_automated"] = True
            else:
                m["fold_automated"] = False

            # Ground-truth claimed status from agent profile
            m["is_claimed"] = bool(agent_profile.get("is_claimed")) if agent_profile else None

            # Per-agent score and threading metrics
            m["total_upvotes"] = ix_upvotes.get(name, 0)
            m["interaction_count"] = ix_counts.get(name, 0)
            m["upvotes_per_interaction"] = (
                round(m["total_upvotes"] / m["interaction_count"], 4)
                if m["interaction_count"] > 0 else 0.0
            )
            m["reply_count"] = reply_counts.get(name, 0)
            m["reply_rate"] = (
                round(m["reply_count"] / m["interaction_count"], 4)
                if m["interaction_count"] > 0 else 0.0
            )

            # Attractor: high follower ratio (10x+) AND 20+ followers
            if m.get("follower_ratio", 0) >= 10 and m.get("follower_count", 0) >= 20:
                roles.append("attractor")

            # Hub: 3+ mutual follows in the scraped graph
            if m.get("mutual_count", 0) >= 3:
                roles.append("hub")

            # Broadcaster: posts in many submolts but no reciprocal embeddedness
            if m.get("submolt_count", 0) >= 5 and not is_fold:
                roles.append("broadcaster")

            m["roles"] = roles

    def _compute_bridging_topology(self) -> None:
        """Compute fold bridging topology: which community pairs do folds bridge?"""
        from itertools import combinations

        self._bridging: dict = {
            "matrix": Counter(),       # (i,j) -> fold count
            "per_community": {},       # community -> {bridges, unique_folds}
            "concentration": 0.0,      # Gini coefficient
            "redundancy": {},          # k -> pairs that lose all bridges when top-k folds removed
        }

        # Collect fold agents and their embedded communities
        fold_agents = []
        for name, m in self._metrics.items():
            if not m.get("is_fold", False):
                continue
            comms = m.get("fold_embedded_communities", [])
            if len(comms) >= 2:
                fold_agents.append((name, comms, m.get("reciprocal_tie_count", 0)))

        if not fold_agents:
            return

        # Build community-pair fold matrix
        pair_folds: dict[tuple[int, int], set[str]] = defaultdict(set)
        for name, comms, _ in fold_agents:
            for ci, cj in combinations(sorted(comms), 2):
                pair_folds[(ci, cj)].add(name)

        # Store counts
        for pair, agents in pair_folds.items():
            self._bridging["matrix"][pair] = len(agents)

        # Per-community stats
        community_bridges: dict[int, set[str]] = defaultdict(set)
        for (ci, cj), agents in pair_folds.items():
            community_bridges[ci].update(agents)
            community_bridges[cj].update(agents)

        for comm in sorted(self._valid_communities):
            folds_here = community_bridges.get(comm, set())
            self._bridging["per_community"][comm] = {
                "bridge_pairs": sum(1 for (ci, cj) in pair_folds if ci == comm or cj == comm),
                "unique_folds": len(folds_here),
            }

        # Gini coefficient of bridge counts
        counts = sorted(self._bridging["matrix"].values())
        if counts:
            n = len(counts)
            total = sum(counts)
            if total > 0:
                numerator = sum((2 * (i + 1) - n - 1) * c for i, c in enumerate(counts))
                self._bridging["concentration"] = numerator / (n * total)

        # Redundancy test: remove top-k folds by reciprocal tie count
        ranked_folds = sorted(fold_agents, key=lambda x: -x[2])
        all_pairs = set(pair_folds.keys())
        total_bridged = len(all_pairs)

        for k in [1, 5, 10, 20]:
            if k > len(ranked_folds):
                break
            removed = {name for name, _, _ in ranked_folds[:k]}
            surviving_pairs = set()
            for pair, agents in pair_folds.items():
                if agents - removed:  # at least one fold survives
                    surviving_pairs.add(pair)
            disconnected = total_bridged - len(surviving_pairs)
            self._bridging["redundancy"][k] = {
                "removed_agents": sorted(removed),
                "total_bridged_pairs": total_bridged,
                "surviving_pairs": len(surviving_pairs),
                "disconnected_pairs": disconnected,
            }

    def _compute_temporal_folds(self) -> None:
        """Track fold formation over time using daily cumulative interaction windows.

        Uses fixed community assignments from the full-dataset analysis.
        Answers: are folds dispositional (form immediately) or emergent (accumulate over time)?
        """
        if not self._interactions or not self._submolt_clusters:
            return

        # Group interactions by date (ISO prefix slicing)
        by_date: dict[str, list[dict]] = defaultdict(list)
        for ix in self._interactions:
            ts = ix.get("timestamp")
            if ts:
                by_date[ts[:10]].append(ix)

        if not by_date:
            return

        dates = sorted(by_date.keys())

        # Fixed community assignments from full analysis
        agent_comms = {n: m.get("primary_community") for n, m in self._metrics.items()}

        # Incremental state
        outgoing: dict[str, set[str]] = defaultdict(set)

        timeline = []
        first_fold_date: dict[str, str] = {}
        prev_folds: set[str] = set()
        cumulative_count = 0

        for day in dates:
            # Add today's interactions to cumulative outgoing set
            for ix in by_date[day]:
                agent = ix.get("agent", "")
                target = ix.get("target_agent", "")
                if agent and target:
                    outgoing[agent].add(target)
            cumulative_count += len(by_date[day])

            # Build reciprocal ties: mutual follows (fixed) + bidirectional interactions
            reciprocal: dict[str, set[str]] = defaultdict(set)
            for name, partners in self._mutual_ties.items():
                reciprocal[name].update(partners)
            for agent, targets in outgoing.items():
                for target in targets:
                    if agent in outgoing.get(target, set()):
                        reciprocal[agent].add(target)
                        reciprocal[target].add(agent)

            # Detect folds with standard criteria
            day_folds: set[str] = set()
            for agent, partners in reciprocal.items():
                pc_counts: Counter = Counter()
                for p in partners:
                    pc = agent_comms.get(p)
                    if pc is not None and pc != -1:
                        pc_counts[pc] += 1
                embedded = [c for c, n in pc_counts.items() if n >= 2]
                if len(embedded) >= 2 and len(partners) >= 5:
                    day_folds.add(agent)
                    if agent not in first_fold_date:
                        first_fold_date[agent] = day

            new_folds = day_folds - prev_folds
            timeline.append({
                "date": day,
                "cumulative_interactions": cumulative_count,
                "fold_count": len(day_folds),
                "new_folds": len(new_folds),
            })
            prev_folds = day_folds

        # Write first_fold_date into per-agent metrics
        for agent, date in first_fold_date.items():
            m = self._metrics.get(agent)
            if m:
                m["first_fold_date"] = date

        self._temporal_folds = {
            "timeline": timeline,
            "first_fold_date": first_fold_date,
        }

    def report(self) -> str:
        """Generate a terminal-friendly analysis report."""
        lines = []
        lines.append("=" * 70)
        lines.append("MOLTBOOK NETWORK CROSS-REFERENCE ANALYSIS")
        lines.append("=" * 70)

        # Summary
        total = len(self._metrics)
        folds = [n for n, m in self._metrics.items() if "fold" in m.get("roles", [])]
        attractors = [n for n, m in self._metrics.items() if "attractor" in m.get("roles", [])]
        hubs = [n for n, m in self._metrics.items() if "hub" in m.get("roles", [])]
        broadcasters = [n for n, m in self._metrics.items() if "broadcaster" in m.get("roles", [])]

        automated_folds = [n for n in folds if self._metrics[n].get("fold_automated", False)]

        lines.append(f"\nAgents analyzed: {total}")
        lines.append(f"Structural folds (reciprocal ties in 2+ cohesive groups): {len(folds)}")
        lines.append(f"  of which automated (karma=0, 1K+ interactions): {len(automated_folds)}")
        lines.append(f"Attractors (10x follower ratio, 20+ followers): {len(attractors)}")
        lines.append(f"Hubs (3+ mutual follows): {len(hubs)}")
        lines.append(f"Broadcasters (5+ submolts, no fold embeddedness): {len(broadcasters)}")

        # Q1: Structural folds — Vedres & Stark definition
        lines.append("\n" + "-" * 70)
        lines.append("Q1: STRUCTURAL FOLDS (reciprocal ties embedded in 2+ cohesive communities)")
        lines.append("-" * 70)
        fold_agents = sorted(
            [(n, m) for n, m in self._metrics.items() if m.get("is_fold", False)],
            key=lambda x: (-x[1].get("fold_community_count", 0), -x[1].get("reciprocal_tie_count", 0)),
        )[:20]
        lines.append(f"{'Agent':<28} {'EmbedIn':>7} {'RecipTies':>9} {'Mutuals':>8} {'Submolts':>9} {'Auto':>5} {'Communities'}")
        lines.append("-" * 100)
        for name, m in fold_agents:
            auto = "yes" if m.get("fold_automated", False) else ""
            lines.append(
                f"{name:<28} {m.get('fold_community_count', 0):>7} "
                f"{m.get('reciprocal_tie_count', 0):>9} {m.get('mutual_tie_count', 0):>8} "
                f"{m.get('submolt_count', 0):>9} {auto:>5} {m.get('fold_embedded_communities', [])}"
            )

        # Q2: Attractors — high followers, low following
        lines.append("\n" + "-" * 70)
        lines.append("Q2: ATTRACTORS (high follower/following ratio)")
        lines.append("-" * 70)
        by_ratio = sorted(
            [(n, m) for n, m in self._metrics.items() if m.get("follower_count", 0) >= 10],
            key=lambda x: x[1].get("follower_ratio", 0),
            reverse=True,
        )[:20]
        lines.append(f"{'Agent':<28} {'Ratio':>7} {'Followers':>10} {'Following':>10} {'Submolts':>9} {'Mutual':>7}")
        lines.append("-" * 90)
        for name, m in by_ratio:
            lines.append(
                f"{name:<28} {m.get('follower_ratio', 0):>7.1f} "
                f"{m.get('follower_count', 0):>10} {m.get('following_count', 0):>10} "
                f"{m.get('submolt_count', 0):>9} {m.get('mutual_count', 0):>7}"
            )

        # Q3: Hubs — high mutual follows, how focused?
        lines.append("\n" + "-" * 70)
        lines.append("Q3: HUBS (most mutual follows — are they focused or broad?)")
        lines.append("-" * 70)
        by_mutual = sorted(
            self._metrics.items(),
            key=lambda x: x[1].get("mutual_count", 0),
            reverse=True,
        )[:20]
        lines.append(f"{'Agent':<28} {'Mutual':>7} {'Submolts':>9} {'Followers':>10} {'Following':>10} {'Roles'}")
        lines.append("-" * 90)
        for name, m in by_mutual:
            if m.get("mutual_count", 0) == 0:
                continue
            roles = ",".join(m.get("roles", [])) or "-"
            lines.append(
                f"{name:<28} {m.get('mutual_count', 0):>7} {m.get('submolt_count', 0):>9} "
                f"{m.get('follower_count', 0):>10} {m.get('following_count', 0):>10} {roles}"
            )

        # Cross-reference: overlap between categories
        lines.append("\n" + "-" * 70)
        lines.append("CROSS-REFERENCE: ROLE OVERLAPS")
        lines.append("-" * 70)

        fold_set = set(folds)
        attractor_set = set(attractors)
        hub_set = set(hubs)

        fold_and_attractor = fold_set & attractor_set
        fold_and_hub = fold_set & hub_set
        attractor_and_hub = attractor_set & hub_set
        all_three = fold_set & attractor_set & hub_set

        lines.append(f"Fold + Attractor: {len(fold_and_attractor)}  {sorted(fold_and_attractor)[:10]}")
        lines.append(f"Fold + Hub:       {len(fold_and_hub)}  {sorted(fold_and_hub)[:10]}")
        lines.append(f"Attractor + Hub:  {len(attractor_and_hub)}  {sorted(attractor_and_hub)[:10]}")
        lines.append(f"All three:        {len(all_three)}  {sorted(all_three)[:10]}")

        # Key insight: do hubs tend to be focused or broad?
        if hubs:
            hub_submolt_counts = [self._metrics[n].get("submolt_count", 0) for n in hubs]
            avg_hub_submolts = sum(hub_submolt_counts) / len(hub_submolt_counts)
            non_hub_with_submolts = [
                m.get("submolt_count", 0)
                for n, m in self._metrics.items()
                if n not in hub_set and m.get("submolt_count", 0) > 0
            ]
            avg_non_hub_submolts = (
                sum(non_hub_with_submolts) / len(non_hub_with_submolts)
                if non_hub_with_submolts else 0
            )
            lines.append(f"\nAvg submolts for hubs: {avg_hub_submolts:.1f}")
            lines.append(f"Avg submolts for non-hubs: {avg_non_hub_submolts:.1f}")
            if avg_hub_submolts > avg_non_hub_submolts * 1.3:
                lines.append("-> Hubs tend to be BROADER (active in more communities)")
            elif avg_hub_submolts < avg_non_hub_submolts * 0.7:
                lines.append("-> Hubs tend to be MORE FOCUSED (concentrated in fewer communities)")
            else:
                lines.append("-> Hubs have similar community breadth to non-hubs")

        # Score-weighted analysis
        lines.append("\n" + "-" * 70)
        lines.append("SCORE-WEIGHTED ANALYSIS: QUALITY VS VOLUME")
        lines.append("-" * 70)

        def _score_row(label: str, agents_list: list[str], show_recip: bool = False) -> str:
            ixs = sum(self._metrics[n].get("interaction_count", 0) for n in agents_list)
            ups = sum(self._metrics[n].get("total_upvotes", 0) for n in agents_list)
            rate = ups / ixs if ixs > 0 else 0.0
            if show_recip:
                rs = sum(self._metrics[n].get("reciprocal_tie_score", 0) for n in agents_list)
                st = sum(self._metrics[n].get("scored_reciprocal_tie_count", 0) for n in agents_list)
                return (
                    f"{label:<24} {len(agents_list):>6} {ixs:>12} {ups:>8} "
                    f"{rate:>10.4f} {rs:>11} {st:>11}"
                )
            return (
                f"{label:<24} {len(agents_list):>6} {ixs:>12} {ups:>8} "
                f"{rate:>10.4f} {'-':>11} {'-':>11}"
            )

        lines.append(
            f"{'':24} {'Agents':>6} {'Interactions':>12} {'Upvotes':>8} "
            f"{'Upvotes/IX':>10} {'RecipScore':>11} {'ScoredTies':>11}"
        )
        claimed_folds = [n for n in folds if self._metrics[n].get("is_claimed") is True]
        unclaimed_folds = [n for n in folds if self._metrics[n].get("is_claimed") is False]
        active_non_folds = [
            n for n, m in self._metrics.items()
            if "fold" not in m.get("roles", []) and m.get("interaction_count", 0) > 0
        ]
        lines.append(_score_row("Folds (claimed)", claimed_folds, show_recip=True))
        lines.append(_score_row("Folds (unclaimed)", unclaimed_folds, show_recip=True))
        lines.append(_score_row("Non-fold active", active_non_folds))

        # Score-filtered fold diagnostic
        if self._score_diagnostics:
            d = self._score_diagnostics
            lines.append(f"\nScore-filtered fold diagnostic:")
            lines.append(f"  Original folds: {d['original_folds']}")
            lines.append(
                f"  Folds with 5+ scored reciprocal ties in 2+ communities: {d['scored_folds']}"
            )
            lost = d["lost"]
            lines.append(f"  Lost fold status: {len(lost)} agents")
            if lost:
                lines.append(f"    {lost[:20]}")
            gained = d["gained"]
            if gained:
                lines.append(f"  Gained fold status: {len(gained)} agents")
                lines.append(f"    {gained[:20]}")
            pct = d["survival_rate"] * 100
            if pct >= 90:
                verdict = "sufficient"
            elif pct >= 70:
                verdict = "mostly sufficient"
            else:
                verdict = "insufficient"
            lines.append(
                f"  -> Volume-based detection is {verdict} "
                f"— {pct:.1f}% of folds survive score filtering"
            )

        # Fold bridging topology
        if self._bridging and self._bridging["matrix"]:
            lines.append("\n" + "-" * 70)
            lines.append("FOLD BRIDGING TOPOLOGY")
            lines.append("-" * 70)

            matrix = self._bridging["matrix"]
            total_pairs = len(matrix)
            total_possible = len(self._valid_communities) * (len(self._valid_communities) - 1) // 2

            lines.append(f"\nBridged community pairs: {total_pairs} / {total_possible} possible")
            lines.append(f"Unbridged pairs: {total_possible - total_pairs}")
            lines.append(f"Gini concentration: {self._bridging['concentration']:.3f}")

            # Top 10 most-bridged pairs
            top_pairs = sorted(matrix.items(), key=lambda x: -x[1])[:10]
            lines.append(f"\n{'Pair':<16} {'Folds':>6}")
            lines.append("-" * 24)
            for (ci, cj), count in top_pairs:
                lines.append(f"({ci:>3}, {cj:>3})      {count:>6}")

            # Most-isolated communities (fewest bridge connections)
            per_comm = self._bridging["per_community"]
            isolated = sorted(per_comm.items(), key=lambda x: x[1]["unique_folds"])[:10]
            lines.append(f"\n{'Community':>10} {'BridgePairs':>12} {'UniqueFolds':>12}")
            lines.append("-" * 36)
            for comm, stats in isolated:
                lines.append(f"{comm:>10} {stats['bridge_pairs']:>12} {stats['unique_folds']:>12}")

            # Redundancy test
            lines.append(f"\nRedundancy test (removing top-k folds by reciprocal tie count):")
            lines.append(f"{'k':>4} {'Surviving':>10} {'Disconnected':>13} {'% Resilient':>12}")
            lines.append("-" * 42)
            for k, stats in sorted(self._bridging["redundancy"].items()):
                total = stats["total_bridged_pairs"]
                surviving = stats["surviving_pairs"]
                pct = (surviving / total * 100) if total else 0
                lines.append(f"{k:>4} {surviving:>10} {stats['disconnected_pairs']:>13} {pct:>11.1f}%")

        # Temporal fold formation
        if self._temporal_folds and self._temporal_folds.get("timeline"):
            lines.append("\n" + "-" * 70)
            lines.append("TEMPORAL FOLD FORMATION")
            lines.append("-" * 70)

            tl = self._temporal_folds["timeline"]
            lines.append(f"\n{'Date':<12} {'CumIX':>8} {'Folds':>6} {'NewFolds':>9}")
            lines.append("-" * 38)
            for row in tl:
                lines.append(
                    f"{row['date']:<12} {row['cumulative_interactions']:>8} "
                    f"{row['fold_count']:>6} {row['new_folds']:>+8}"
                )

            ffd = self._temporal_folds.get("first_fold_date", {})
            if ffd:
                sorted_dates = sorted(ffd.values())
                total = len(sorted_dates)
                lines.append(f"\nFormation summary:")
                lines.append(f"  First fold appeared: {sorted_dates[0]}")

                # Percentile dates
                for pct_label, pct_val in [("50%", 0.5), ("90%", 0.9)]:
                    idx = min(int(total * pct_val), total - 1)
                    count = idx + 1
                    lines.append(f"  {pct_label} of folds ({count}) by: {sorted_dates[idx]}")
                lines.append(f"  All {total} folds by: {sorted_dates[-1]}")

                # Burst analysis: what % formed during Feb 4-8?
                burst_folds = sum(1 for d in sorted_dates if "2026-02-04" <= d <= "2026-02-08")
                burst_pct = burst_folds / total * 100 if total else 0
                lines.append(
                    f"  Formed during Feb 4-8 burst (85% of interactions): "
                    f"{burst_folds}/{total} ({burst_pct:.1f}%)"
                )
                if burst_pct >= 90:
                    lines.append("  -> DISPOSITIONAL: folds form during the initial growth wave")
                elif burst_pct >= 70:
                    lines.append("  -> MOSTLY DISPOSITIONAL: most folds form during the burst, some emerge later")
                else:
                    lines.append("  -> EMERGENT: folds continue accumulating after the burst")

        lines.append("\n" + "=" * 70)
        return "\n".join(lines)

    def to_json(self) -> dict:
        """Export full analysis as JSON."""
        # Serialize bridging matrix with string keys for JSON
        bridging_json = {}
        if self._bridging and self._bridging["matrix"]:
            bridging_json = {
                "matrix": {f"{ci},{cj}": count for (ci, cj), count in self._bridging["matrix"].items()},
                "per_community": self._bridging["per_community"],
                "concentration_gini": self._bridging["concentration"],
                "redundancy": self._bridging["redundancy"],
            }

        return {
            "agent_count": len(self._metrics),
            "fold_detection_active": bool(self._submolt_clusters),
            "agents": self._metrics,
            "summary": {
                "folds": [n for n, m in self._metrics.items() if "fold" in m.get("roles", [])],
                "attractors": [n for n, m in self._metrics.items() if "attractor" in m.get("roles", [])],
                "hubs": [n for n, m in self._metrics.items() if "hub" in m.get("roles", [])],
                "broadcasters": [n for n, m in self._metrics.items() if "broadcaster" in m.get("roles", [])],
            },
            "bridging_topology": bridging_json,
            "score_diagnostics": self._score_diagnostics,
            "temporal_folds": self._temporal_folds,
        }

    def save_json(self, path: str) -> None:
        """Write analysis JSON to disk."""
        data = self.to_json()
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2, default=str))
        print(f"Analysis saved to {out}")
