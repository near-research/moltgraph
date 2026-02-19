"""Generate a findings dashboard — a self-contained HTML page with 5 panels
visualizing the key structural findings from the Moltbook network analysis.

Reads data/analysis.json (primary) and data/overlap_graphs.json (community labels)
and produces output/dashboard.html.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


class DashboardGenerator:
    def __init__(
        self,
        analysis_path: str = "data/analysis.json",
        overlap_graphs_path: str = "data/overlap_graphs.json",
    ):
        self._analysis = json.loads(Path(analysis_path).read_text())
        self._overlap = json.loads(Path(overlap_graphs_path).read_text())
        self._community_labels = self._build_community_labels()

    def _build_community_labels(self) -> dict[int, str]:
        """Map community ID → top submolt name by author_count."""
        po = self._overlap.get("post_overlap", {})
        nodes = po.get("nodes", [])
        comm: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for n in nodes:
            c = n.get("community")
            if c is not None and c not in (0, 283):
                comm[c].append((n.get("author_count", 0), n["id"]))
        return {c: max(members, key=lambda x: x[0])[1] for c, members in comm.items() if members}

    def _extract_bridging(self) -> dict:
        """Panel 1: The Triangle — 28-node community graph."""
        bt = self._analysis["bridging_topology"]

        nodes = []
        for c_str, info in bt["per_community"].items():
            c = int(c_str)
            nodes.append({
                "id": c,
                "bridge_pairs": info["bridge_pairs"],
                "unique_folds": info["unique_folds"],
                "in_triangle": c in {1, 3, 6},
                "label": self._community_labels.get(c, f"C{c}"),
            })

        edges = []
        for pair_str, count in bt["matrix"].items():
            ci, cj = pair_str.split(",")
            edges.append({
                "source": int(ci),
                "target": int(cj),
                "fold_count": count,
            })

        zero_bridge = [n["id"] for n in nodes if n["unique_folds"] == 0]

        return {
            "nodes": nodes,
            "edges": edges,
            "gini": round(bt["concentration_gini"], 3),
            "total_bridged": len(bt["matrix"]),
            "total_possible": 28 * 27 // 2,
            "zero_bridge_communities": zero_bridge,
        }

    def _extract_ownership(self) -> dict:
        """Panel 2: Ownership Gap — per-community claimed/unclaimed."""
        agents = self._analysis["agents"]
        bt = self._analysis["bridging_topology"]
        folds = {n: m for n, m in agents.items() if m.get("is_fold")}

        comm_ownership: dict[int, dict] = {}
        for c_str in bt["per_community"]:
            c = int(c_str)
            comm_ownership[c] = {"total": 0, "claimed": 0, "unclaimed": 0}

        for m in folds.values():
            c = m.get("primary_community")
            if c is None:
                # Assign to first embedded community
                embedded = m.get("fold_embedded_communities", [])
                c = embedded[0] if embedded else None
            if c is not None and c in comm_ownership:
                comm_ownership[c]["total"] += 1
                if m.get("is_claimed"):
                    comm_ownership[c]["claimed"] += 1
                else:
                    comm_ownership[c]["unclaimed"] += 1

        for info in comm_ownership.values():
            info["claimed_pct"] = round(info["claimed"] / info["total"] * 100, 1) if info["total"] > 0 else 0

        total_folds = len(folds)
        total_claimed = sum(1 for m in folds.values() if m.get("is_claimed"))

        return {
            "per_community": comm_ownership,
            "total_folds": total_folds,
            "total_claimed": total_claimed,
            "total_unclaimed": total_folds - total_claimed,
            "claimed_pct": round(total_claimed / total_folds * 100, 1),
        }

    def _extract_timeline(self) -> list[dict]:
        """Panel 3: Temporal Formation — already in correct shape."""
        return self._analysis["temporal_folds"]["timeline"]

    def _extract_fold_scatter(self) -> list[dict]:
        """Panel 4: Quality vs Volume — 271 fold dots."""
        agents = self._analysis["agents"]
        folds = []
        for name, m in agents.items():
            if not m.get("is_fold"):
                continue
            folds.append({
                "name": name,
                "x": m.get("reciprocal_tie_count", 0),
                "y": m.get("upvotes_per_interaction", 0),
                "scored": m.get("scored_reciprocal_tie_count", 0) > 0,
                "automated": m.get("fold_automated", False),
                "community": m.get("primary_community"),
                "interaction_count": m.get("interaction_count", 0),
            })
        return folds

    def _extract_broadcast(self) -> dict:
        """Panel 5: Broadcast Structure — summary stats."""
        agents = self._analysis["agents"]
        total = len(agents)
        total_ix = sum(m.get("interaction_count", 0) for m in agents.values())
        total_replies = sum(m.get("reply_count", 0) for m in agents.values())
        with_ix = sorted(
            [(n, m["interaction_count"]) for n, m in agents.items() if m.get("interaction_count", 0) > 0],
            key=lambda x: -x[1],
        )
        top10_ix = sum(c for _, c in with_ix[:10])

        return {
            "total_agents": total,
            "post_only_pct": round((total - len(with_ix)) / total * 100, 1),
            "root_level_pct": round((total_ix - total_replies) / total_ix * 100, 1) if total_ix else 0,
            "top10_share_pct": round(top10_ix / total_ix * 100, 1) if total_ix else 0,
            "top10": [{"name": n, "count": c} for n, c in with_ix[:10]],
            "total_interactions": total_ix,
            "follow_edges": sum(1 for m in agents.values() if m.get("following_count", 0) > 0),
            "mutual_pairs": sum(m.get("mutual_count", 0) for m in agents.values()) // 2,
            "fold_count": sum(1 for m in agents.values() if m.get("is_fold")),
        }

    def _extract_data(self) -> dict:
        return {
            "bridging": self._extract_bridging(),
            "ownership": self._extract_ownership(),
            "timeline": self._extract_timeline(),
            "scatter": self._extract_fold_scatter(),
            "broadcast": self._extract_broadcast(),
        }

    def generate(self, output_path: str = "output/dashboard.html") -> None:
        data = self._extract_data()
        data_json = json.dumps(data, separators=(",", ":"))
        data_json = data_json.replace("</", "<\\/")
        html = self._build_html(data_json)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html)
        print(f"Dashboard -> {out}")

    def _build_html(self, data_json: str) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Moltgraph — Findings Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<style>
:root {{
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --accent: #58a6ff;
  --gold: #e3b341;
  --red: #da3633;
  --green: #3fb950;
  --text: #c9d1d9;
  --muted: #8b949e;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  line-height: 1.5;
}}
.container {{
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
}}

/* Header */
header {{
  text-align: center;
  padding: 40px 0 32px;
}}
header h1 {{
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 8px;
}}
header p {{
  color: var(--muted);
  font-size: 14px;
}}

/* Panels */
.panel {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 20px;
}}
.panel h2 {{
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 4px;
}}
.panel .subtitle {{
  color: var(--muted);
  font-size: 13px;
  margin-bottom: 16px;
  line-height: 1.4;
}}

/* Grid layouts */
.grid-2 {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}}

/* Stats row below panels */
.stat-row {{
  display: flex;
  gap: 24px;
  justify-content: center;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}}
.stat-item {{
  text-align: center;
}}
.stat-item .val {{
  font-size: 20px;
  font-weight: 700;
  color: var(--accent);
}}
.stat-item .label {{
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}}

/* Hero stats for broadcast panel */
.hero-stats {{
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
  margin-bottom: 20px;
}}
.hero-stat {{
  text-align: center;
  padding: 16px;
  background: var(--bg);
  border-radius: 8px;
}}
.hero-stat .num {{
  font-size: 32px;
  font-weight: 700;
  color: var(--accent);
}}
.hero-stat .desc {{
  font-size: 12px;
  color: var(--muted);
  margin-top: 4px;
}}

/* Bar chart */
.bar-row {{
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 12px;
}}
.bar-row .name {{
  width: 140px;
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
}}
.bar-row .bar-bg {{
  flex: 1;
  height: 14px;
  background: var(--bg);
  border-radius: 3px;
  overflow: hidden;
}}
.bar-row .bar-fill {{
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
}}
.bar-row .count {{
  width: 50px;
  font-size: 11px;
  color: var(--muted);
}}

/* SVG containers */
.chart-container {{
  width: 100%;
  overflow: visible;
}}
.chart-container svg {{
  width: 100%;
  display: block;
}}

/* Tooltip */
#tooltip {{
  position: fixed;
  pointer-events: none;
  display: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 12px;
  max-width: 260px;
  z-index: 100;
  line-height: 1.5;
  box-shadow: 0 4px 12px rgba(0,0,0,0.5);
}}
#tooltip strong {{ color: var(--accent); }}
#tooltip .detail {{ color: var(--muted); font-size: 11px; }}

/* Legend */
.legend {{
  display: flex;
  gap: 16px;
  justify-content: center;
  margin-top: 12px;
  font-size: 12px;
  color: var(--muted);
}}
.legend-item {{
  display: flex;
  align-items: center;
  gap: 4px;
}}
.legend-dot {{
  width: 10px;
  height: 10px;
  border-radius: 50%;
}}

/* Footer */
footer {{
  text-align: center;
  padding: 24px 0 48px;
  font-size: 12px;
  color: var(--muted);
}}
footer a {{
  color: var(--accent);
  text-decoration: none;
}}
footer a:hover {{ text-decoration: underline; }}

/* Node labels */
.node-label {{
  fill: var(--text);
  font-size: 10px;
  pointer-events: none;
  text-anchor: middle;
}}

/* Scatter */
.scatter-dot {{
  cursor: pointer;
  stroke-width: 1;
}}
.scatter-dot:hover {{
  stroke-width: 2;
  stroke: white;
}}

/* Axis */
.axis text {{ fill: var(--muted); font-size: 11px; }}
.axis line, .axis path {{ stroke: var(--border); }}
.axis-label {{ fill: var(--muted); font-size: 11px; }}

@media (max-width: 800px) {{
  .grid-2 {{ grid-template-columns: 1fr; }}
  .hero-stats {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>

<div class="container">
  <header>
    <h1>Moltgraph</h1>
    <p>Structural findings from a 21-day-old AI agent platform</p>
  </header>

  <!-- Panel 1: The Triangle (hero) -->
  <div class="panel" id="panel-triangle">
    <h2>The Mandatory Triangle</h2>
    <p class="subtitle">28 posting-overlap communities, connected by 271 structural folds. Three communities form a core triangle that every fold must pass through. 11 communities have zero fold bridges — structural blind spots.</p>
    <div class="chart-container" id="triangle-chart"></div>
    <div class="legend" id="triangle-legend">
      <span class="legend-item"><span class="legend-dot" style="background:#58a6ff"></span> Triangle community</span>
      <span class="legend-item"><span class="legend-dot" style="background:#8b949e"></span> Bridged community</span>
      <span class="legend-item"><span class="legend-dot" style="background:#da3633"></span> Zero bridges</span>
      <span class="legend-item"><span class="legend-dot" style="background:#e3b341;width:16px;height:2px;border-radius:1px"></span> Triangle edge</span>
    </div>
    <div class="stat-row" id="triangle-stats"></div>
  </div>

  <div class="grid-2">
    <!-- Panel 2: Ownership Gap -->
    <div class="panel" id="panel-ownership">
      <h2>Ownership Gap</h2>
      <p class="subtitle">Same communities, colored by what fraction of their folds are claimed. The structurally dominant communities are also the least accountable.</p>
      <div class="chart-container" id="ownership-chart"></div>
      <div class="legend" id="ownership-legend"></div>
      <div class="stat-row" id="ownership-stats"></div>
    </div>

    <!-- Panel 3: Temporal Formation -->
    <div class="panel" id="panel-temporal">
      <h2>Temporal Formation</h2>
      <p class="subtitle">Fold emergence tracks interaction volume — a dispositional signal. Folds form as conversation accumulates, not from external coordination.</p>
      <div class="chart-container" id="temporal-chart"></div>
    </div>
  </div>

  <div class="grid-2">
    <!-- Panel 4: Quality vs Volume -->
    <div class="panel" id="panel-scatter">
      <h2>Quality vs Volume</h2>
      <p class="subtitle">Each dot is one fold agent. Most folds are volume-embedded only — high reciprocal ties but low upvote rates. Score-validated folds (blue) survive quality filtering.</p>
      <div class="chart-container" id="scatter-chart"></div>
      <div class="legend" id="scatter-legend">
        <span class="legend-item"><span class="legend-dot" style="background:#58a6ff"></span> Score-validated</span>
        <span class="legend-item"><span class="legend-dot" style="background:#8b949e"></span> Volume-only</span>
        <span class="legend-item"><span class="legend-dot" style="background:#e3b341"></span> Automated</span>
      </div>
    </div>

    <!-- Panel 5: Broadcast Structure -->
    <div class="panel" id="panel-broadcast">
      <h2>Broadcast Structure</h2>
      <p class="subtitle">The platform is a parasocial broadcast network. Most agents only post, most comments are root-level, and a handful of agents generate nearly half of all activity.</p>
      <div id="broadcast-content"></div>
    </div>
  </div>

  <footer>
    <p>
      <a href="overlap.html">Community Overlap</a> &middot;
      <a href="follows.html">Follow Graph</a> &middot;
      <a href="interactions.html">Interaction Graph</a> &middot;
      <a href="https://github.com/jlwaugh/moltgraph">Source</a>
    </p>
  </footer>
</div>

<div id="tooltip"></div>

<script>
const D = {data_json};
const tooltip = d3.select("#tooltip");

function showTip(e, html) {{
  tooltip.html(html).style("display", "block")
    .style("left", (e.clientX + 14) + "px")
    .style("top", (e.clientY - 14) + "px");
}}
function hideTip() {{ tooltip.style("display", "none"); }}

// ── Panel 1: The Triangle ──────────────────────────────────
(function() {{
  const B = D.bridging;
  const W = 1140, H = 480;
  const svg = d3.select("#triangle-chart").append("svg")
    .attr("viewBox", `0 0 ${{W}} ${{H}}`);

  const rScale = d3.scaleSqrt()
    .domain([0, d3.max(B.nodes, d => d.unique_folds)])
    .range([6, 40]);
  const wScale = d3.scaleLinear()
    .domain([0, d3.max(B.edges, d => d.fold_count)])
    .range([0.5, 6]);

  function nodeColor(d) {{
    if (d.in_triangle) return "#58a6ff";
    if (d.unique_folds === 0) return "#da3633";
    return "#8b949e";
  }}

  const sim = d3.forceSimulation(B.nodes)
    .force("link", d3.forceLink(B.edges).id(d => d.id).distance(100).strength(d => d.fold_count / 200))
    .force("charge", d3.forceManyBody().strength(-300))
    .force("center", d3.forceCenter(W / 2, H / 2))
    .force("collision", d3.forceCollide().radius(d => rScale(d.unique_folds) + 8));

  const linkEls = svg.append("g").selectAll("line").data(B.edges)
    .join("line")
    .attr("stroke", d => {{
      const s = B.nodes.find(n => n.id === (d.source.id ?? d.source));
      const t = B.nodes.find(n => n.id === (d.target.id ?? d.target));
      return (s && s.in_triangle && t && t.in_triangle) ? "#e3b341" : "#30363d";
    }})
    .attr("stroke-opacity", d => {{
      const s = B.nodes.find(n => n.id === (d.source.id ?? d.source));
      const t = B.nodes.find(n => n.id === (d.target.id ?? d.target));
      return (s && s.in_triangle && t && t.in_triangle) ? 0.7 : 0.3;
    }})
    .attr("stroke-width", d => wScale(d.fold_count));

  const nodeGs = svg.append("g").selectAll("g").data(B.nodes)
    .join("g").attr("cursor", "pointer")
    .on("mouseover", (e, d) => {{
      const conns = B.edges.filter(l =>
        (l.source.id ?? l.source) === d.id || (l.target.id ?? l.target) === d.id
      ).sort((a, b) => b.fold_count - a.fold_count).slice(0, 5);
      const connHtml = conns.map(l => {{
        const other = (l.source.id ?? l.source) === d.id
          ? (l.target.id ?? l.target) : (l.source.id ?? l.source);
        const label = B.nodes.find(n => n.id === other)?.label || other;
        return `<div class="detail">↔ ${{label}} (${{l.fold_count}} folds)</div>`;
      }}).join("");
      showTip(e, `<strong>C${{d.id}}: ${{d.label}}</strong><br>
        Folds: ${{d.unique_folds}}<br>Bridge pairs: ${{d.bridge_pairs}}<br>${{connHtml}}`);
    }})
    .on("mousemove", (e) => {{
      tooltip.style("left", (e.clientX + 14) + "px").style("top", (e.clientY - 14) + "px");
    }})
    .on("mouseout", hideTip);

  nodeGs.append("circle")
    .attr("r", d => rScale(d.unique_folds))
    .attr("fill", nodeColor)
    .attr("stroke", d => d3.color(nodeColor(d)).darker(0.5))
    .attr("stroke-width", 1.5);

  nodeGs.append("text")
    .attr("class", "node-label")
    .attr("dy", d => rScale(d.unique_folds) + 14)
    .text(d => d.label.length > 16 ? d.label.slice(0, 14) + "..." : d.label)
    .style("font-size", "9px");

  // Store final positions for Panel 2
  sim.on("tick", () => {{
    linkEls
      .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    nodeGs.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
  }});

  // After simulation settles, capture positions for Panel 2
  sim.on("end", () => {{
    window._trianglePositions = {{}};
    B.nodes.forEach(d => {{ window._trianglePositions[d.id] = {{x: d.x, y: d.y}}; }});
    renderOwnership();
  }});

  // Stats
  document.getElementById("triangle-stats").innerHTML = `
    <div class="stat-item"><span class="val">${{B.total_bridged}}</span><span class="label">of ${{B.total_possible}} pairs bridged</span></div>
    <div class="stat-item"><span class="val">${{B.gini}}</span><span class="label">Gini concentration</span></div>
    <div class="stat-item"><span class="val">${{B.zero_bridge_communities.length}}</span><span class="label">Communities with zero bridges</span></div>
  `;
}})();

// ── Panel 2: Ownership Gap ──────────────────────────────────
function renderOwnership() {{
  const O = D.ownership;
  const B = D.bridging;
  const pos = window._trianglePositions;
  if (!pos) return;

  const W = 540, H = 400;

  // Compute bounding box from Panel 1 positions and remap to Panel 2 size
  const xs = B.nodes.map(n => pos[n.id]?.x || 0);
  const ys = B.nodes.map(n => pos[n.id]?.y || 0);
  const pad = 50;
  const xScale = d3.scaleLinear().domain([d3.min(xs) - pad, d3.max(xs) + pad]).range([pad, W - pad]);
  const yScale = d3.scaleLinear().domain([d3.min(ys) - pad, d3.max(ys) + pad]).range([pad, H - pad]);

  const svg = d3.select("#ownership-chart").append("svg")
    .attr("viewBox", `0 0 ${{W}} ${{H}}`);

  const rScale = d3.scaleSqrt()
    .domain([0, d3.max(B.nodes, d => d.unique_folds)])
    .range([4, 28]);

  const claimedScale = d3.scaleSequential(d3.interpolateRdYlGn).domain([0, 100]);

  // Draw edges (muted)
  svg.append("g").selectAll("line").data(B.edges)
    .join("line")
    .attr("x1", d => xScale(pos[d.source.id ?? d.source]?.x || 0))
    .attr("y1", d => yScale(pos[d.source.id ?? d.source]?.y || 0))
    .attr("x2", d => xScale(pos[d.target.id ?? d.target]?.x || 0))
    .attr("y2", d => yScale(pos[d.target.id ?? d.target]?.y || 0))
    .attr("stroke", "#30363d")
    .attr("stroke-opacity", 0.15)
    .attr("stroke-width", 0.5);

  // Draw nodes
  const nodeGs = svg.append("g").selectAll("g").data(B.nodes)
    .join("g")
    .attr("transform", d => {{
      const p = pos[d.id];
      return `translate(${{xScale(p?.x || 0)}},${{yScale(p?.y || 0)}})`;
    }})
    .attr("cursor", "pointer")
    .on("mouseover", (e, d) => {{
      const ow = O.per_community[d.id] || {{total: 0, claimed: 0, unclaimed: 0, claimed_pct: 0}};
      showTip(e, `<strong>C${{d.id}}: ${{d.label}}</strong><br>
        Folds: ${{ow.total}}<br>Claimed: ${{ow.claimed}}<br>Unclaimed: ${{ow.unclaimed}}<br>
        Claimed: ${{ow.claimed_pct}}%`);
    }})
    .on("mousemove", (e) => {{
      tooltip.style("left", (e.clientX + 14) + "px").style("top", (e.clientY - 14) + "px");
    }})
    .on("mouseout", hideTip);

  nodeGs.append("circle")
    .attr("r", d => rScale(d.unique_folds))
    .attr("fill", d => {{
      const ow = O.per_community[d.id];
      if (!ow || ow.total === 0) return "#30363d";
      return claimedScale(ow.claimed_pct);
    }})
    .attr("stroke", d => {{
      const ow = O.per_community[d.id];
      if (!ow || ow.total === 0) return "#30363d";
      return d3.color(claimedScale(ow.claimed_pct)).darker(0.5);
    }})
    .attr("stroke-width", 1.5);

  nodeGs.append("text")
    .attr("class", "node-label")
    .attr("dy", d => rScale(d.unique_folds) + 12)
    .text(d => d.label.length > 14 ? d.label.slice(0, 12) + "..." : d.label)
    .style("font-size", "8px");

  // Legend: color gradient
  const lgW = 200, lgH = 12;
  const lgSvg = d3.select("#ownership-legend").append("svg")
    .attr("width", lgW + 60).attr("height", lgH + 20);
  const defs = lgSvg.append("defs");
  const grad = defs.append("linearGradient").attr("id", "claim-grad");
  grad.append("stop").attr("offset", "0%").attr("stop-color", d3.interpolateRdYlGn(0));
  grad.append("stop").attr("offset", "50%").attr("stop-color", d3.interpolateRdYlGn(0.5));
  grad.append("stop").attr("offset", "100%").attr("stop-color", d3.interpolateRdYlGn(1));
  lgSvg.append("rect").attr("x", 30).attr("y", 4).attr("width", lgW).attr("height", lgH)
    .attr("fill", "url(#claim-grad)").attr("rx", 3);
  lgSvg.append("text").attr("x", 28).attr("y", lgH + 16).attr("text-anchor", "end")
    .attr("fill", "#8b949e").attr("font-size", 10).text("0%");
  lgSvg.append("text").attr("x", 32 + lgW).attr("y", lgH + 16)
    .attr("fill", "#8b949e").attr("font-size", 10).text("100%");

  document.getElementById("ownership-stats").innerHTML = `
    <div class="stat-item"><span class="val">${{O.total_unclaimed}}</span><span class="label">of ${{O.total_folds}} folds unclaimed</span></div>
    <div class="stat-item"><span class="val">${{O.claimed_pct}}%</span><span class="label">claimed rate</span></div>
  `;
}}

// ── Panel 3: Temporal Formation ──────────────────────────────
(function() {{
  const T = D.timeline;
  const margin = {{top: 20, right: 60, bottom: 40, left: 50}};
  const W = 540, H = 320;
  const w = W - margin.left - margin.right;
  const h = H - margin.top - margin.bottom;

  const svg = d3.select("#temporal-chart").append("svg")
    .attr("viewBox", `0 0 ${{W}} ${{H}}`)
    .append("g").attr("transform", `translate(${{margin.left}},${{margin.top}})`);

  const parseDate = d3.timeParse("%Y-%m-%d");
  T.forEach(d => {{ d._date = parseDate(d.date); }});

  const x = d3.scaleTime()
    .domain(d3.extent(T, d => d._date))
    .range([0, w]);

  const yFolds = d3.scaleLinear()
    .domain([0, d3.max(T, d => d.fold_count)])
    .range([h, 0]);

  const yInteractions = d3.scaleLinear()
    .domain([0, d3.max(T, d => d.cumulative_interactions)])
    .range([h, 0]);

  // X axis
  svg.append("g").attr("class", "axis")
    .attr("transform", `translate(0,${{h}})`)
    .call(d3.axisBottom(x).ticks(6).tickFormat(d3.timeFormat("%b %d")));

  // Left Y axis (folds)
  svg.append("g").attr("class", "axis")
    .call(d3.axisLeft(yFolds).ticks(5));
  svg.append("text").attr("class", "axis-label")
    .attr("transform", "rotate(-90)")
    .attr("x", -h / 2).attr("y", -38)
    .attr("text-anchor", "middle")
    .text("Cumulative folds");

  // Right Y axis (interactions)
  svg.append("g").attr("class", "axis")
    .attr("transform", `translate(${{w}},0)`)
    .call(d3.axisRight(yInteractions).ticks(5).tickFormat(d => d >= 1000 ? (d / 1000) + "K" : d));
  svg.append("text").attr("class", "axis-label")
    .attr("transform", "rotate(90)")
    .attr("x", h / 2).attr("y", -w - 45)
    .attr("text-anchor", "middle")
    .text("Cumulative interactions");

  // Area for interactions
  const area = d3.area()
    .x(d => x(d._date))
    .y0(h)
    .y1(d => yInteractions(d.cumulative_interactions))
    .curve(d3.curveMonotoneX);
  svg.append("path").datum(T)
    .attr("d", area)
    .attr("fill", "#30363d")
    .attr("fill-opacity", 0.5);

  // Line for folds
  const line = d3.line()
    .x(d => x(d._date))
    .y(d => yFolds(d.fold_count))
    .curve(d3.curveStepAfter);
  svg.append("path").datum(T)
    .attr("d", line)
    .attr("fill", "none")
    .attr("stroke", "#58a6ff")
    .attr("stroke-width", 2.5);

  // Dots on fold line
  svg.selectAll(".fold-dot").data(T)
    .join("circle").attr("class", "fold-dot")
    .attr("cx", d => x(d._date))
    .attr("cy", d => yFolds(d.fold_count))
    .attr("r", 3)
    .attr("fill", "#58a6ff")
    .on("mouseover", (e, d) => showTip(e,
      `<strong>${{d.date}}</strong><br>Folds: ${{d.fold_count}} (+${{d.new_folds}})<br>Interactions: ${{d.cumulative_interactions.toLocaleString()}}`))
    .on("mousemove", (e) => {{
      tooltip.style("left", (e.clientX + 14) + "px").style("top", (e.clientY - 14) + "px");
    }})
    .on("mouseout", hideTip);

  // Legend
  svg.append("circle").attr("cx", w - 160).attr("cy", 10).attr("r", 4).attr("fill", "#58a6ff");
  svg.append("text").attr("x", w - 152).attr("y", 14).attr("fill", "#8b949e").attr("font-size", 11).text("Folds");
  svg.append("rect").attr("x", w - 100).attr("y", 6).attr("width", 12).attr("height", 8).attr("fill", "#30363d").attr("fill-opacity", 0.5);
  svg.append("text").attr("x", w - 84).attr("y", 14).attr("fill", "#8b949e").attr("font-size", 11).text("Interactions");
}})();

// ── Panel 4: Quality vs Volume ──────────────────────────────
(function() {{
  const S = D.scatter;
  const margin = {{top: 20, right: 20, bottom: 40, left: 50}};
  const W = 540, H = 360;
  const w = W - margin.left - margin.right;
  const h = H - margin.top - margin.bottom;

  const svg = d3.select("#scatter-chart").append("svg")
    .attr("viewBox", `0 0 ${{W}} ${{H}}`)
    .append("g").attr("transform", `translate(${{margin.left}},${{margin.top}})`);

  const x = d3.scaleLog()
    .domain([d3.min(S, d => d.x) * 0.8, d3.max(S, d => d.x) * 1.2])
    .range([0, w]);

  const y = d3.scaleLinear()
    .domain([0, d3.max(S, d => d.y) * 1.1])
    .range([h, 0]);

  svg.append("g").attr("class", "axis")
    .attr("transform", `translate(0,${{h}})`)
    .call(d3.axisBottom(x).ticks(5, "~s"));
  svg.append("text").attr("class", "axis-label")
    .attr("x", w / 2).attr("y", h + 34)
    .attr("text-anchor", "middle")
    .text("Reciprocal tie count");

  svg.append("g").attr("class", "axis")
    .call(d3.axisLeft(y).ticks(5));
  svg.append("text").attr("class", "axis-label")
    .attr("transform", "rotate(-90)")
    .attr("x", -h / 2).attr("y", -38)
    .attr("text-anchor", "middle")
    .text("Upvotes per interaction");

  function dotColor(d) {{
    if (d.automated) return "#e3b341";
    if (d.scored) return "#58a6ff";
    return "#8b949e";
  }}

  // Sort so scored dots render on top
  const sorted = [...S].sort((a, b) => {{
    const order = d => d.automated ? 0 : d.scored ? 2 : 1;
    return order(a) - order(b);
  }});

  svg.selectAll(".scatter-dot").data(sorted)
    .join("circle").attr("class", "scatter-dot")
    .attr("cx", d => x(d.x))
    .attr("cy", d => y(d.y))
    .attr("r", d => d.automated ? 5 : 3.5)
    .attr("fill", dotColor)
    .attr("fill-opacity", 0.75)
    .attr("stroke", d => d3.color(dotColor(d)).darker(0.4))
    .on("mouseover", (e, d) => showTip(e,
      `<strong>${{d.name}}</strong><br>
       Reciprocal ties: ${{d.x}}<br>
       Upvote rate: ${{d.y.toFixed(3)}}<br>
       Interactions: ${{d.interaction_count.toLocaleString()}}<br>
       <span class="detail">${{d.scored ? "Score-validated" : d.automated ? "Automated" : "Volume-only"}}</span>`))
    .on("mousemove", (e) => {{
      tooltip.style("left", (e.clientX + 14) + "px").style("top", (e.clientY - 14) + "px");
    }})
    .on("mouseout", hideTip);

  // Annotation
  const scored = S.filter(d => d.scored).length;
  const volumeOnly = S.filter(d => !d.scored && !d.automated).length;
  const automated = S.filter(d => d.automated).length;
  svg.append("text")
    .attr("x", w).attr("y", 12).attr("text-anchor", "end")
    .attr("fill", "#8b949e").attr("font-size", 11)
    .text(`${{scored}} score-validated · ${{volumeOnly}} volume-only · ${{automated}} automated`);
}})();

// ── Panel 5: Broadcast Structure ──────────────────────────────
(function() {{
  const BC = D.broadcast;
  const el = document.getElementById("broadcast-content");

  const heroHtml = `
    <div class="hero-stats">
      <div class="hero-stat">
        <div class="num">${{BC.post_only_pct}}%</div>
        <div class="desc">of agents have zero interactions</div>
      </div>
      <div class="hero-stat">
        <div class="num">${{BC.root_level_pct}}%</div>
        <div class="desc">of comments are root-level</div>
      </div>
      <div class="hero-stat">
        <div class="num">${{BC.top10_share_pct}}%</div>
        <div class="desc">of activity from top 10 agents</div>
      </div>
    </div>
  `;

  const maxCount = BC.top10[0]?.count || 1;
  const barsHtml = BC.top10.map(d => `
    <div class="bar-row">
      <span class="name">${{d.name}}</span>
      <span class="bar-bg"><span class="bar-fill" style="width:${{d.count / maxCount * 100}}%"></span></span>
      <span class="count">${{(d.count / 1000).toFixed(0)}}K</span>
    </div>
  `).join("");

  const summaryHtml = `
    <div class="stat-row" style="margin-top:16px">
      <div class="stat-item"><span class="val">${{BC.fold_count}}</span><span class="label">structural folds</span></div>
      <div class="stat-item"><span class="val">${{(BC.total_interactions / 1000).toFixed(0)}}K</span><span class="label">total interactions</span></div>
      <div class="stat-item"><span class="val">${{BC.total_agents.toLocaleString()}}</span><span class="label">agents</span></div>
    </div>
  `;

  el.innerHTML = heroHtml + barsHtml + summaryHtml;
}})();
</script>
</body>
</html>"""


def main() -> None:
    gen = DashboardGenerator()
    gen.generate()


if __name__ == "__main__":
    main()
