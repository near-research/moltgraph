"""Generate a self-contained HTML visualization from graph JSON."""

from __future__ import annotations

import json
from pathlib import Path


class Visualizer:
    """Renders graph data as a single self-contained HTML file with D3.js."""

    def __init__(self, graph_data: dict) -> None:
        self._data = graph_data

    def render(self, output_path: str = "output/index.html") -> None:
        """Write the visualization HTML to disk."""
        html = self._build_html()
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html)
        print(f"Visualization → {out}")

    def _build_html(self) -> str:
        graph_json = json.dumps(self._data, separators=(",", ":"))
        graph_json = graph_json.replace("</", "<\\/")
        node_count = len(self._data.get("nodes", []))
        is_follow = self._data.get("graph_type") == "follow"

        title = "Moltbook Follow Network" if is_follow else "Moltbook Network"
        chord_label = "follows" if is_follow else "interactions"
        stat4_label = "Mutual Pairs" if is_follow else "Avg Clustering"
        stat4_id = "stat-mutual" if is_follow else "stat-clustering"
        top10_label = "Top 10 (Followers)" if is_follow else "Top 10 (Betweenness)"
        weight_filter_display = "none" if is_follow else "block"
        mutual_btn_display = "block" if is_follow else "none"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<style>
:root {{
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --accent: #58a6ff;
  --mutual: #e3b341;
  --text: #c9d1d9;
  --muted: #8b949e;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}}

/* Top bar */
#topbar {{
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  z-index: 10;
}}
#topbar h1 {{
  font-size: 14px;
  font-weight: 600;
  margin-right: 16px;
  white-space: nowrap;
}}
.tab-btn {{
  padding: 5px 14px;
  border-radius: 20px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}}
.tab-btn.active {{
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}}
.tab-btn:hover:not(.active) {{ border-color: var(--muted); color: var(--text); }}
.spacer {{ flex: 1; }}
.ctrl-btn {{
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--muted);
  cursor: pointer;
  font-size: 11px;
}}
.ctrl-btn:hover {{ border-color: var(--accent); color: var(--accent); }}

/* Main area */
#main {{
  flex: 1;
  display: flex;
  position: relative;
  overflow: hidden;
}}

/* Views */
.view {{ display: none; width: 100%; height: 100%; position: absolute; top: 0; left: 0; }}
.view.active {{ display: flex; }}
#chord-view {{ justify-content: center; align-items: center; }}
#force-view {{ position: relative; }}
#force-svg {{ width: 100%; height: 100%; }}
#chord-svg {{ max-width: 100%; max-height: 100%; }}

/* Warning banner */
#warning-banner {{
  display: none;
  position: absolute;
  top: 8px;
  left: 50%;
  transform: translateX(-50%);
  background: #da3633;
  color: #fff;
  padding: 6px 16px;
  border-radius: 6px;
  font-size: 12px;
  z-index: 20;
}}

/* Filter panel */
#filter-panel {{
  position: absolute;
  top: 8px;
  left: 8px;
  width: 220px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  z-index: 15;
  font-size: 12px;
}}
#filter-panel h3 {{ font-size: 11px; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; letter-spacing: 0.5px; }}
.filter-row {{ margin-bottom: 10px; }}
.filter-row label {{ display: block; margin-bottom: 4px; color: var(--muted); }}
.filter-row input[type="range"] {{ width: 100%; accent-color: var(--accent); }}
.filter-row .val {{ float: right; color: var(--accent); font-weight: 600; }}
#ego-btn, #mutual-btn {{
  width: 100%;
  padding: 6px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text);
  cursor: pointer;
  font-size: 12px;
  margin-bottom: 6px;
}}
#ego-btn:hover, #mutual-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
#ego-btn.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
#mutual-btn.active {{ background: var(--mutual); color: #000; border-color: var(--mutual); }}
#filter-toggle {{
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 16;
}}

/* Sidebar */
#sidebar {{
  width: 280px;
  min-width: 280px;
  background: var(--surface);
  border-left: 1px solid var(--border);
  overflow-y: auto;
  padding: 16px;
  font-size: 12px;
  flex-shrink: 0;
  transition: margin-right 0.3s;
}}
#sidebar.collapsed {{ margin-right: -280px; }}
#sidebar-toggle {{
  position: absolute;
  top: 50%;
  right: 280px;
  transform: translateY(-50%);
  z-index: 15;
  background: var(--surface);
  border: 1px solid var(--border);
  border-right: none;
  border-radius: 6px 0 0 6px;
  padding: 8px 4px;
  cursor: pointer;
  color: var(--muted);
  font-size: 10px;
  transition: right 0.3s;
}}
#sidebar-toggle.collapsed {{ right: 0; }}
.sidebar-section {{ margin-bottom: 16px; }}
.sidebar-section h3 {{
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--muted);
  margin-bottom: 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border);
}}
.stat-row {{ display: flex; justify-content: space-between; margin-bottom: 4px; }}
.stat-val {{ color: var(--accent); font-weight: 600; }}
#search-input {{
  width: 100%;
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  font-size: 12px;
  outline: none;
}}
#search-input:focus {{ border-color: var(--accent); }}
.top10-item {{
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}}
.top10-item .swatch {{
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}}
.top10-item .name {{ flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.top10-item .bar-wrap {{
  width: 60px;
  height: 6px;
  background: var(--bg);
  border-radius: 3px;
  overflow: hidden;
  flex-shrink: 0;
}}
.top10-item .bar {{
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
}}
.community-row {{
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}}
.community-row .swatch {{
  width: 10px;
  height: 10px;
  border-radius: 3px;
  flex-shrink: 0;
}}

/* Tooltip */
#tooltip {{
  position: absolute;
  pointer-events: none;
  display: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 12px;
  max-width: 240px;
  z-index: 100;
  line-height: 1.5;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}}
#tooltip strong {{ color: var(--accent); }}
#tooltip .conn {{ color: var(--muted); font-size: 11px; }}
#tooltip .mutual-badge {{ color: var(--mutual); font-weight: 600; }}

/* Node styles */
.node-circle {{ cursor: pointer; stroke-width: 1.5px; }}
.node-circle.pinned {{ stroke-dasharray: 3,2; }}
.node-label {{
  fill: var(--text);
  font-size: 9px;
  pointer-events: none;
  text-anchor: middle;
  dominant-baseline: central;
  opacity: 0;
}}
.node-circle:hover + .node-label {{ opacity: 1; }}
</style>
</head>
<body>

<div id="topbar">
  <h1>{title}</h1>
  <button class="tab-btn active" data-view="chord">Overview (Chord)</button>
  <button class="tab-btn" data-view="force">Network (Force)</button>
  <div class="spacer"></div>
  <button class="ctrl-btn" id="btn-zoom-in" title="Zoom In">+</button>
  <button class="ctrl-btn" id="btn-zoom-out" title="Zoom Out">&minus;</button>
  <button class="ctrl-btn" id="btn-reset" title="Reset View">Reset</button>
  <button class="ctrl-btn" id="btn-restart" title="Restart Simulation">Restart</button>
  <button class="ctrl-btn" id="btn-labels" title="Toggle Edge Labels">Labels</button>
</div>

<div id="main">
  <div id="chord-view" class="view active">
    <svg id="chord-svg"></svg>
  </div>
  <div id="force-view" class="view">
    <div id="warning-banner"></div>
    <div id="filter-panel">
      <h3>Filters</h3>
      <div class="filter-row" style="display:{weight_filter_display}">
        <label>Min edge weight <span class="val" id="weight-val">2</span></label>
        <input type="range" id="weight-slider" min="1" max="20" value="2">
      </div>
      <div class="filter-row">
        <label>Top N nodes <span class="val" id="topn-val">100</span></label>
        <input type="range" id="topn-slider" min="10" max="500" value="100">
      </div>
      <button id="mutual-btn" style="display:{mutual_btn_display}">Mutual Only</button>
      <button id="ego-btn">Show Ego Network</button>
    </div>
    <svg id="force-svg"></svg>
  </div>

  <button id="sidebar-toggle">&lsaquo;</button>
  <div id="sidebar">
    <div class="sidebar-section">
      <h3>Network Stats</h3>
      <div class="stat-row"><span>Nodes</span><span class="stat-val" id="stat-nodes">0</span></div>
      <div class="stat-row"><span>Edges</span><span class="stat-val" id="stat-edges">0</span></div>
      <div class="stat-row"><span>Density</span><span class="stat-val" id="stat-density">0</span></div>
      <div class="stat-row"><span>{stat4_label}</span><span class="stat-val" id="{stat4_id}">0</span></div>
    </div>
    <div class="sidebar-section">
      <h3>Search</h3>
      <input type="text" id="search-input" placeholder="Search agents...">
    </div>
    <div class="sidebar-section">
      <h3>{top10_label}</h3>
      <div id="top10-list"></div>
    </div>
    <div class="sidebar-section">
      <h3>Communities</h3>
      <div id="community-list"></div>
    </div>
  </div>
</div>

<div id="tooltip"></div>

<script>
const GRAPH_DATA = {graph_json};

(function() {{
  "use strict";

  const nodes = GRAPH_DATA.nodes;
  const edges = GRAPH_DATA.edges;
  const isFollow = GRAPH_DATA.graph_type === "follow";
  const color = d3.scaleOrdinal(d3.schemeTableau10);

  if (!nodes.length) {{
    document.getElementById("main").innerHTML =
      '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--muted);font-size:18px;">No data to visualize</div>';
    return;
  }}

  /* ============ SIDEBAR ============ */
  const nodeMap = new Map(nodes.map(n => [n.id, n]));
  const maxBetweenness = d3.max(nodes, d => d.betweenness) || 1;
  const maxFollowers = d3.max(nodes, d => d.follower_count) || 1;
  const maxWeight = d3.max(edges, d => d.weight) || 1;

  // Stats
  const edgeCount = edges.length;
  const nodeCount = nodes.length;
  const density = nodeCount > 1 ? (edgeCount / (nodeCount * (nodeCount - 1))).toFixed(4) : "0";

  document.getElementById("stat-nodes").textContent = nodeCount;
  document.getElementById("stat-edges").textContent = edgeCount;
  document.getElementById("stat-density").textContent = density;

  if (isFollow) {{
    const mutualPairs = edges.filter(e => e.mutual).length / 2;
    const el = document.getElementById("stat-mutual");
    if (el) el.textContent = Math.floor(mutualPairs);
  }} else {{
    // Avg clustering on undirected adjacency
    const adj = new Map(nodes.map(n => [n.id, new Set()]));
    edges.forEach(e => {{
      if (adj.has(e.source)) adj.get(e.source).add(e.target);
      if (adj.has(e.target)) adj.get(e.target).add(e.source);
    }});
    let clusterSum = 0;
    adj.forEach((neighbors, node) => {{
      const ns = [...neighbors];
      if (ns.length < 2) return;
      let triangles = 0;
      for (let i = 0; i < ns.length; i++)
        for (let j = i + 1; j < ns.length; j++)
          if (adj.get(ns[i])?.has(ns[j])) triangles++;
      clusterSum += (2 * triangles) / (ns.length * (ns.length - 1));
    }});
    const avgClustering = (clusterSum / nodeCount).toFixed(4);
    const el = document.getElementById("stat-clustering");
    if (el) el.textContent = avgClustering;
  }}

  // Top 10
  const top10 = isFollow
    ? [...nodes].sort((a, b) => (b.follower_count || 0) - (a.follower_count || 0)).slice(0, 10)
    : [...nodes].sort((a, b) => b.betweenness - a.betweenness).slice(0, 10);
  const top10Max = isFollow ? maxFollowers : maxBetweenness;
  const top10El = document.getElementById("top10-list");
  top10.forEach(d => {{
    const val = isFollow ? (d.follower_count || 0) : d.betweenness;
    const pct = top10Max > 0 ? (val / top10Max) * 100 : 0;
    top10El.innerHTML += `<div class="top10-item">
      <span class="swatch" style="background:${{color(d.community)}}"></span>
      <span class="name" title="${{d.id}}">${{d.display_name}}</span>
      <span class="bar-wrap"><span class="bar" style="width:${{pct}}%"></span></span>
    </div>`;
  }});

  // Communities
  const communityMap = d3.group(nodes, d => d.community);
  const commEl = document.getElementById("community-list");
  [...communityMap.entries()]
    .sort((a, b) => b[1].length - a[1].length)
    .forEach(([cid, members]) => {{
      commEl.innerHTML += `<div class="community-row">
        <span class="swatch" style="background:${{color(cid)}}"></span>
        <span>Community ${{cid}}</span>
        <span class="stat-val">${{members.length}}</span>
      </div>`;
    }});

  // Sidebar toggle
  const sidebar = document.getElementById("sidebar");
  const sidebarToggle = document.getElementById("sidebar-toggle");
  sidebarToggle.addEventListener("click", () => {{
    sidebar.classList.toggle("collapsed");
    sidebarToggle.classList.toggle("collapsed");
    sidebarToggle.textContent = sidebar.classList.contains("collapsed") ? "\\u203a" : "\\u2039";
  }});

  /* ============ TAB SWITCHING ============ */
  let currentView = "chord";
  document.querySelectorAll(".tab-btn").forEach(btn => {{
    btn.addEventListener("click", () => {{
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const view = btn.dataset.view;
      currentView = view;
      document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
      document.getElementById(view + "-view").classList.add("active");
      if (view === "force" && !forceInitialized) initForceGraph();
    }});
  }});

  /* ============ CHORD DIAGRAM ============ */
  (function initChord() {{
    const communities = [...new Set(nodes.map(n => n.community))].sort((a, b) => a - b);
    const n = communities.length;
    if (n === 0) return;

    const cidx = new Map(communities.map((c, i) => [c, i]));
    const matrix = Array.from({{ length: n }}, () => new Array(n).fill(0));

    const nodeCommunity = new Map(nodes.map(nd => [nd.id, nd.community]));
    edges.forEach(e => {{
      const sc = nodeCommunity.get(e.source);
      const tc = nodeCommunity.get(e.target);
      if (sc !== undefined && tc !== undefined) {{
        matrix[cidx.get(sc)][cidx.get(tc)] += e.weight;
      }}
    }});

    const svgEl = document.getElementById("chord-svg");
    const size = Math.min(window.innerWidth - 300, window.innerHeight - 60, 700);
    const outerRadius = size / 2 - 40;
    const innerRadius = outerRadius - 20;

    const svg = d3.select("#chord-svg")
      .attr("width", size)
      .attr("height", size)
      .attr("viewBox", [-size / 2, -size / 2, size, size]);

    const chord = d3.chord()
      .padAngle(0.04)
      .sortSubgroups(d3.descending);

    const chords = chord(matrix);

    const arc = d3.arc().innerRadius(innerRadius).outerRadius(outerRadius);
    const ribbon = d3.ribbon().radius(innerRadius);

    const tooltip = d3.select("#tooltip");
    const edgeLabel = isFollow ? "follows" : "interactions";

    // Ribbons
    svg.append("g")
      .selectAll("path")
      .data(chords)
      .join("path")
        .attr("d", ribbon)
        .attr("fill", d => color(communities[d.source.index]))
        .attr("stroke", "none")
        .attr("opacity", 0.6)
        .on("mouseover", function(event, d) {{
          d3.select(this).attr("opacity", 0.9);
          const src = communities[d.source.index];
          const tgt = communities[d.target.index];
          const val = d.source.value;
          tooltip.style("display", "block")
            .html(`<strong>Community ${{src}} &rarr; ${{tgt}}</strong><br>${{val}} ${{edgeLabel}}`);
          positionTooltip(event);
        }})
        .on("mousemove", positionTooltip)
        .on("mouseout", function() {{
          d3.select(this).attr("opacity", 0.6);
          tooltip.style("display", "none");
        }})
        .on("click", function(event, d) {{
          const cid = communities[d.source.index];
          document.querySelector('[data-view="force"]').click();
        }});

    // Arcs
    const arcGroup = svg.append("g")
      .selectAll("g")
      .data(chords.groups)
      .join("g");

    arcGroup.append("path")
      .attr("d", arc)
      .attr("fill", d => color(communities[d.index]))
      .attr("stroke", "#0d1117")
      .attr("stroke-width", 1)
      .on("mouseover", function(event, d) {{
        svg.selectAll("path").attr("opacity", 0.15);
        d3.select(this).attr("opacity", 1);
        svg.selectAll("path")
          .filter(function() {{ return this.parentNode.tagName === "g" && !d3.select(this).datum()?.index; }})
          .attr("opacity", 0.15);
        const cid = communities[d.index];
        const memberCount = communityMap.get(cid)?.length || 0;
        tooltip.style("display", "block")
          .html(`<strong>Community ${{cid}}</strong><br>${{memberCount}} agents`);
        positionTooltip(event);
      }})
      .on("mousemove", positionTooltip)
      .on("mouseout", function() {{
        svg.selectAll("path").attr("opacity", 0.6);
        arcGroup.selectAll("path").attr("opacity", 1);
        tooltip.style("display", "none");
      }});

    // Labels
    arcGroup.append("text")
      .each(d => {{ d.angle = (d.startAngle + d.endAngle) / 2; }})
      .attr("dy", "0.35em")
      .attr("transform", d => `
        rotate(${{(d.angle * 180 / Math.PI - 90)}})
        translate(${{outerRadius + 10}})
        ${{d.angle > Math.PI ? "rotate(180)" : ""}}
      `)
      .attr("text-anchor", d => d.angle > Math.PI ? "end" : null)
      .attr("fill", "var(--text)")
      .attr("font-size", "11px")
      .text(d => `C${{communities[d.index]}} (${{communityMap.get(communities[d.index])?.length || 0}})`);
  }})();

  /* ============ FORCE-DIRECTED GRAPH ============ */
  let forceInitialized = false;
  let simulation, forceLink, forceNode, forceNodeLabel, forceEdgeLabel;
  let forceZoom;
  let selectedNode = null;
  let egoMode = false;
  let mutualOnly = false;

  // Scales — adapt based on graph type
  const nodeSizeMetric = isFollow ? "follower_count" : "betweenness";
  const maxNodeMetric = isFollow ? maxFollowers : maxBetweenness;
  const nodeRadiusScale = d3.scaleSqrt().domain([0, maxNodeMetric || 1]).range([6, 30]);
  const edgeWidthScale = d3.scaleLinear().domain([1, maxWeight]).range([1, 6]);
  const edgeOpacityScale = d3.scaleLinear().domain([1, maxWeight]).range([0.3, 0.9]);

  function nodeRadius(d) {{
    return nodeRadiusScale(isFollow ? (d.follower_count || 0) : d.betweenness);
  }}

  // Working copies for filtering
  let filteredNodes = [...nodes];
  let filteredEdges = [...edges];
  let minWeight = isFollow ? 1 : 2;
  let topN = Math.min(100, nodes.length);

  const largeGraph = {node_count} > 500;

  function initForceGraph() {{
    forceInitialized = true;

    if (largeGraph) {{
      const banner = document.getElementById("warning-banner");
      banner.style.display = "block";
      banner.textContent = `Large graph (${{nodes.length}} nodes) — filters applied for performance`;
    }}

    // Update slider max
    document.getElementById("topn-slider").max = nodes.length;
    document.getElementById("topn-slider").value = topN;
    document.getElementById("topn-val").textContent = topN;
    document.getElementById("weight-slider").value = minWeight;
    document.getElementById("weight-val").textContent = minWeight;

    const svgEl = document.getElementById("force-svg");
    const width = svgEl.clientWidth;
    const height = svgEl.clientHeight;

    const svg = d3.select("#force-svg");
    const defs = svg.append("defs");
    const g = svg.append("g");

    // Zoom
    forceZoom = d3.zoom()
      .scaleExtent([0.1, 10])
      .on("zoom", event => g.attr("transform", event.transform));
    svg.call(forceZoom);

    // Reset focus on background click
    svg.on("click", () => {{
      if (egoMode) return;
      selectedNode = null;
      resetHighlight();
    }});

    // Arrow markers
    defs.append("marker")
      .attr("id", "arrow")
      .attr("viewBox", "0 -4 8 8")
      .attr("refX", 8)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-4L8,0L0,4")
      .attr("fill", "var(--muted)");

    defs.append("marker")
      .attr("id", "arrow-mutual")
      .attr("viewBox", "0 -4 8 8")
      .attr("refX", 8)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-4L8,0L0,4")
      .attr("fill", "var(--mutual)");

    // Container groups (order matters for z-index)
    const linkG = g.append("g").attr("class", "links");
    const labelG = g.append("g").attr("class", "edge-labels");
    const nodeG = g.append("g").attr("class", "nodes");
    const nodeLabelG = g.append("g").attr("class", "node-labels");

    function applyFilters() {{
      // Top N by the relevant metric
      const sortedNodes = isFollow
        ? [...nodes].sort((a, b) => (b.follower_count || 0) - (a.follower_count || 0))
        : [...nodes].sort((a, b) => b.betweenness - a.betweenness);
      const topNodeIds = new Set(sortedNodes.slice(0, topN).map(n => n.id));
      filteredNodes = nodes.filter(n => topNodeIds.has(n.id));
      const nodeIdSet = new Set(filteredNodes.map(n => n.id));

      // Filter edges by weight, connected nodes, and mutual-only toggle
      filteredEdges = edges.filter(e =>
        e.weight >= minWeight &&
        nodeIdSet.has(e.source?.id || e.source) &&
        nodeIdSet.has(e.target?.id || e.target) &&
        (!mutualOnly || e.mutual)
      );

      // Remove nodes with no edges after filtering
      const connectedIds = new Set();
      filteredEdges.forEach(e => {{
        connectedIds.add(e.source?.id || e.source);
        connectedIds.add(e.target?.id || e.target);
      }});
      filteredNodes = filteredNodes.filter(n => connectedIds.has(n.id));
    }}

    function renderGraph() {{
      // Deep copy to avoid D3 mutation issues
      const simNodes = filteredNodes.map(n => ({{ ...n }}));
      const simEdges = filteredEdges.map(e => ({{
        source: e.source?.id || e.source,
        target: e.target?.id || e.target,
        weight: e.weight,
        mutual: e.mutual || false,
        upvotes: e.upvotes,
      }}));

      // Links — curved bezier paths
      forceLink = linkG.selectAll("path").data(simEdges, d => d.source + "-" + d.target);
      forceLink.exit().remove();
      forceLink = forceLink.enter().append("path")
        .merge(forceLink)
        .attr("fill", "none")
        .attr("stroke", d => (isFollow && d.mutual) ? "var(--mutual)" : "var(--muted)")
        .attr("stroke-width", d => (isFollow && d.mutual) ? 2.5 : (isFollow ? 1 : edgeWidthScale(d.weight)))
        .attr("stroke-opacity", d => (isFollow && d.mutual) ? 0.8 : (isFollow ? 0.3 : edgeOpacityScale(d.weight)))
        .attr("marker-end", d => (isFollow && d.mutual) ? "url(#arrow-mutual)" : "url(#arrow)");

      // Edge labels
      forceEdgeLabel = labelG.selectAll("text").data(simEdges, d => d.source + "-" + d.target);
      forceEdgeLabel.exit().remove();
      forceEdgeLabel = forceEdgeLabel.enter().append("text")
        .merge(forceEdgeLabel)
        .attr("fill", "var(--muted)")
        .attr("font-size", "9px")
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "central")
        .style("display", "none")
        .text(d => isFollow ? (d.mutual ? "mutual" : "") : d.weight);

      // Nodes
      forceNode = nodeG.selectAll("circle").data(simNodes, d => d.id);
      forceNode.exit().remove();
      forceNode = forceNode.enter().append("circle")
        .attr("class", "node-circle")
        .merge(forceNode)
        .attr("r", nodeRadius)
        .attr("fill", d => color(d.community))
        .attr("stroke", d => d3.color(color(d.community)).brighter(0.6))
        .call(drag());

      // Node interactions
      forceNode
        .on("mouseover", function(event, d) {{
          let html;
          if (isFollow) {{
            const mutualCount = simEdges.filter(e => {{
              const sid = e.source?.id || e.source;
              const tid = e.target?.id || e.target;
              return e.mutual && (sid === d.id || tid === d.id);
            }}).length / 2;
            const followingInGraph = simEdges.filter(e => (e.source?.id || e.source) === d.id);
            const followersInGraph = simEdges.filter(e => (e.target?.id || e.target) === d.id);
            html = `<strong>${{d.display_name}}</strong><br>
              Followers: ${{(d.follower_count || 0).toLocaleString()}}<br>
              Following: ${{(d.following_count || 0).toLocaleString()}}<br>
              <span class="mutual-badge">Mutual: ${{Math.floor(mutualCount)}}</span><br>
              Community: ${{d.community}}`;
          }} else {{
            const conns = simEdges
              .filter(e => (e.source?.id || e.source) === d.id || (e.target?.id || e.target) === d.id)
              .sort((a, b) => b.weight - a.weight)
              .slice(0, 3)
              .map(e => {{
                const other = (e.source?.id || e.source) === d.id ? (e.target?.id || e.target) : (e.source?.id || e.source);
                return `${{other}} (${{e.weight}})`;
              }});
            html = `<strong>${{d.display_name}}</strong><br>
              Karma: ${{(d.karma || 0).toLocaleString()}}<br>
              Posts: ${{d.post_count || 0}}<br>
              Community: ${{d.community}}<br>
              <span class="conn">Top connections:<br>${{conns.map(c => "\\u2022 " + c).join("<br>")}}</span>`;
          }}
          tooltip.style("display", "block").html(html);
          positionTooltip(event);
        }})
        .on("mousemove", positionTooltip)
        .on("mouseout", () => tooltip.style("display", "none"))
        .on("click", function(event, d) {{
          event.stopPropagation();
          if (d.pinned) {{
            d.fx = null; d.fy = null; d.pinned = false;
            d3.select(this).classed("pinned", false);
          }} else {{
            d.fx = d.x; d.fy = d.y; d.pinned = true;
            d3.select(this).classed("pinned", true);
          }}
          selectedNode = d;
          simulation.alphaTarget(0.1).restart();
          setTimeout(() => simulation.alphaTarget(0), 300);
        }})
        .on("dblclick", function(event, d) {{
          event.stopPropagation();
          event.preventDefault();
          highlightNeighborhood(d, simEdges);
        }});

      // Node labels
      forceNodeLabel = nodeLabelG.selectAll("text").data(simNodes, d => d.id);
      forceNodeLabel.exit().remove();
      forceNodeLabel = forceNodeLabel.enter().append("text")
        .attr("class", "node-label")
        .merge(forceNodeLabel)
        .text(d => d.display_name);

      // Simulation
      if (simulation) simulation.stop();
      simulation = d3.forceSimulation(simNodes)
        .force("link", d3.forceLink(simEdges).id(d => d.id).distance(80).strength(0.3))
        .force("charge", d3.forceManyBody().strength(-300))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("collide", d3.forceCollide().radius(d => nodeRadius(d) + 4))
        .alphaDecay(largeGraph ? 0.05 : 0.02)
        .on("tick", ticked);

      function ticked() {{
        forceLink.attr("d", d => {{
          const sx = d.source.x, sy = d.source.y;
          const tx = d.target.x, ty = d.target.y;
          const dx = tx - sx, dy = ty - sy;
          const dist = Math.hypot(dx, dy) || 1;
          const r = nodeRadius(d.target) + 10;
          const ex = tx - (dx / dist) * r;
          const ey = ty - (dy / dist) * r;

          // Check if reverse edge exists for curved path
          const hasReverse = simEdges.some(e =>
            (e.source?.id || e.source) === (d.target?.id || d.target) &&
            (e.target?.id || e.target) === (d.source?.id || d.source)
          );
          if (hasReverse) {{
            const mx = (sx + ex) / 2;
            const my = (sy + ey) / 2;
            const nx2 = -(ey - sy);
            const ny2 = (ex - sx);
            const nl = Math.hypot(nx2, ny2) || 1;
            const curve = 30;
            const cx = mx + (nx2 / nl) * curve;
            const cy = my + (ny2 / nl) * curve;
            return `M${{sx}},${{sy}} Q${{cx}},${{cy}} ${{ex}},${{ey}}`;
          }}
          return `M${{sx}},${{sy}} L${{ex}},${{ey}}`;
        }});

        forceNode.attr("cx", d => d.x).attr("cy", d => d.y);
        forceNodeLabel.attr("x", d => d.x).attr("y", d => d.y - nodeRadius(d) - 4);
        forceEdgeLabel
          .attr("x", d => (d.source.x + d.target.x) / 2)
          .attr("y", d => (d.source.y + d.target.y) / 2);
      }}
    }}

    function highlightNeighborhood(d, simEdges) {{
      const neighborIds = new Set();
      simEdges.forEach(e => {{
        const sid = e.source?.id || e.source;
        const tid = e.target?.id || e.target;
        if (sid === d.id) neighborIds.add(tid);
        if (tid === d.id) neighborIds.add(sid);
      }});
      neighborIds.add(d.id);

      forceNode.attr("opacity", n => neighborIds.has(n.id) ? 1 : 0.08);
      forceLink.attr("stroke-opacity", e => {{
        const sid = e.source?.id || e.source;
        const tid = e.target?.id || e.target;
        if (sid === d.id || tid === d.id) {{
          return (isFollow && e.mutual) ? 0.8 : edgeOpacityScale(e.weight);
        }}
        return 0.02;
      }});
      forceNodeLabel.attr("opacity", n => neighborIds.has(n.id) ? 1 : 0);
    }}

    function resetHighlight() {{
      forceNode.attr("opacity", 1);
      forceLink.attr("stroke-opacity", d => (isFollow && d.mutual) ? 0.8 : (isFollow ? 0.3 : edgeOpacityScale(d.weight)));
      forceNodeLabel.attr("opacity", 0);
    }}

    function drag() {{
      return d3.drag()
        .on("start", (event, d) => {{
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        }})
        .on("drag", (event, d) => {{
          d.fx = event.x; d.fy = event.y;
        }})
        .on("end", (event, d) => {{
          if (!event.active) simulation.alphaTarget(0);
          // Keep pinned
        }});
    }}

    // Initial render
    applyFilters();
    renderGraph();

    // Filter controls
    document.getElementById("weight-slider").addEventListener("input", function() {{
      minWeight = +this.value;
      document.getElementById("weight-val").textContent = minWeight;
      applyFilters();
      renderGraph();
    }});

    document.getElementById("topn-slider").addEventListener("input", function() {{
      topN = +this.value;
      document.getElementById("topn-val").textContent = topN;
      applyFilters();
      renderGraph();
    }});

    // Mutual only toggle (follow graphs)
    document.getElementById("mutual-btn").addEventListener("click", function() {{
      mutualOnly = !mutualOnly;
      this.classList.toggle("active");
      this.textContent = mutualOnly ? "Show All" : "Mutual Only";
      applyFilters();
      renderGraph();
    }});

    document.getElementById("ego-btn").addEventListener("click", function() {{
      egoMode = !egoMode;
      this.classList.toggle("active");
      if (egoMode && selectedNode) {{
        highlightNeighborhood(selectedNode, filteredEdges.map(e => ({{
          source: e.source?.id || e.source,
          target: e.target?.id || e.target,
          weight: e.weight,
          mutual: e.mutual || false,
        }})));
      }} else {{
        resetHighlight();
      }}
    }});

    // Zoom controls
    document.getElementById("btn-zoom-in").addEventListener("click", () =>
      d3.select("#force-svg").transition().duration(300).call(forceZoom.scaleBy, 1.5));
    document.getElementById("btn-zoom-out").addEventListener("click", () =>
      d3.select("#force-svg").transition().duration(300).call(forceZoom.scaleBy, 0.67));
    document.getElementById("btn-reset").addEventListener("click", () =>
      d3.select("#force-svg").transition().duration(750).call(forceZoom.transform, d3.zoomIdentity));
    document.getElementById("btn-restart").addEventListener("click", () => {{
      if (simulation) simulation.alpha(1).restart();
    }});

    // Edge labels toggle
    let labelsVisible = false;
    document.getElementById("btn-labels").addEventListener("click", () => {{
      labelsVisible = !labelsVisible;
      if (forceEdgeLabel) forceEdgeLabel.style("display", labelsVisible ? "block" : "none");
    }});
  }}

  /* ============ SEARCH ============ */
  document.getElementById("search-input").addEventListener("input", function() {{
    const term = this.value.toLowerCase();
    if (!term) {{
      if (forceNode) forceNode.attr("opacity", 1).attr("stroke-width", 1.5);
      return;
    }}
    if (currentView === "force" && forceNode) {{
      forceNode
        .attr("opacity", d => d.id.toLowerCase().includes(term) || d.display_name.toLowerCase().includes(term) ? 1 : 0.1)
        .attr("stroke-width", d => d.id.toLowerCase().includes(term) || d.display_name.toLowerCase().includes(term) ? 3 : 1.5);
    }}
  }});

  /* ============ TOOLTIP HELPER ============ */
  const tooltip = d3.select("#tooltip");
  function positionTooltip(event) {{
    let left = event.pageX + 12;
    let top = event.pageY - 10;
    if (left + 240 > window.innerWidth) left = event.pageX - 252;
    if (top + 160 > window.innerHeight) top = event.pageY - 170;
    tooltip.style("left", left + "px").style("top", top + "px");
  }}

}})();
</script>
</body>
</html>"""
