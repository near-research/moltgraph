"""Generate self-contained HTML visualization of three-layer submolt overlap network.

Reads data/overlap_graphs.json (containing post_overlap, comment_overlap,
engagement_overlap) and produces output/overlap.html — an interactive
force-directed graph with a toggle between the three overlap layers.
"""

from __future__ import annotations

import json
from pathlib import Path

GRAPH_PATH = "data/overlap_graphs.json"
OUTPUT_PATH = "output/overlap.html"


def build_html(layers: dict) -> str:
    layers_json = json.dumps(layers, separators=(",", ":"))
    layers_json = layers_json.replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Moltbook Submolt Overlap Network</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<style>
:root {{
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --accent: #58a6ff;
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

#topbar {{
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  z-index: 10;
}}
#topbar h1 {{ font-size: 14px; font-weight: 600; white-space: nowrap; }}
#topbar .stat {{ font-size: 12px; color: var(--muted); }}
#topbar .stat b {{ color: var(--accent); }}
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

/* Layer toggle */
.layer-toggle {{
  display: flex;
  gap: 0;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}}
.layer-btn {{
  padding: 4px 12px;
  background: var(--surface);
  color: var(--muted);
  cursor: pointer;
  font-size: 11px;
  border: none;
  border-right: 1px solid var(--border);
  transition: all 0.15s;
}}
.layer-btn:last-child {{ border-right: none; }}
.layer-btn:hover {{ color: var(--text); }}
.layer-btn.active {{
  background: var(--accent);
  color: #0d1117;
  font-weight: 600;
}}

#main {{ flex: 1; display: flex; position: relative; overflow: hidden; }}
#force-svg {{ width: 100%; height: 100%; }}

/* Filter panel */
#filter-panel {{
  position: absolute;
  top: 8px;
  left: 8px;
  width: 240px;
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
#search-input {{
  width: 100%;
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  font-size: 12px;
  outline: none;
  margin-bottom: 8px;
}}
#search-input:focus {{ border-color: var(--accent); }}

/* Sidebar */
#sidebar {{
  width: 300px;
  min-width: 300px;
  background: var(--surface);
  border-left: 1px solid var(--border);
  overflow-y: auto;
  padding: 16px;
  font-size: 12px;
  flex-shrink: 0;
}}
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
.top-item {{
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  cursor: pointer;
}}
.top-item:hover {{ color: var(--accent); }}
.top-item .swatch {{
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}}
.top-item .name {{ flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.top-item .bar-wrap {{
  width: 60px;
  height: 6px;
  background: var(--bg);
  border-radius: 3px;
  overflow: hidden;
  flex-shrink: 0;
}}
.top-item .bar {{
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
}}
.community-row {{
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  cursor: pointer;
}}
.community-row:hover {{ color: var(--accent); }}
.community-row .swatch {{
  width: 10px;
  height: 10px;
  border-radius: 3px;
  flex-shrink: 0;
}}

.layer-desc {{
  font-size: 11px;
  color: var(--muted);
  line-height: 1.4;
  margin-bottom: 12px;
  padding: 8px;
  background: var(--bg);
  border-radius: 6px;
  border-left: 3px solid var(--accent);
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
  max-width: 280px;
  z-index: 100;
  line-height: 1.5;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}}
#tooltip strong {{ color: var(--accent); }}
#tooltip .detail {{ color: var(--muted); font-size: 11px; }}

.node-circle {{ cursor: pointer; stroke-width: 1.5px; }}
.node-label {{
  fill: var(--text);
  font-size: 9px;
  pointer-events: none;
  text-anchor: middle;
  dominant-baseline: central;
}}
</style>
</head>
<body>

<div id="topbar">
  <h1>Submolt Overlap Network</h1>
  <div class="layer-toggle" id="layer-toggle"></div>
  <span class="stat" id="stat-nodes"><b>0</b> submolts</span>
  <span class="stat" id="stat-edges"><b>0</b> edges</span>
  <div class="spacer"></div>
  <button class="ctrl-btn" id="btn-zoom-in" title="Zoom In">+</button>
  <button class="ctrl-btn" id="btn-zoom-out" title="Zoom Out">&minus;</button>
  <button class="ctrl-btn" id="btn-reset" title="Reset View">Reset</button>
</div>

<div id="main">
  <svg id="force-svg"></svg>

  <div id="filter-panel">
    <h3>Filters</h3>
    <input type="text" id="search-input" placeholder="Search submolts...">
    <div class="filter-row">
      <label>Min shared agents <span class="val" id="val-shared">1</span></label>
      <input type="range" id="filter-shared" min="1" max="50" value="1">
    </div>
    <div class="filter-row">
      <label>Min agents in submolt <span class="val" id="val-authors">5</span></label>
      <input type="range" id="filter-authors" min="1" max="200" value="5">
    </div>
    <div class="filter-row">
      <label>Min Jaccard similarity <span class="val" id="val-jaccard">0.01</span></label>
      <input type="range" id="filter-jaccard" min="0" max="100" value="1">
    </div>
    <div class="filter-row">
      <label><input type="checkbox" id="toggle-labels" checked> Show labels</label>
    </div>
  </div>

  <div id="sidebar">
    <div class="sidebar-section">
      <h3>Layer</h3>
      <div id="layer-description" class="layer-desc"></div>
    </div>
    <div class="sidebar-section">
      <h3>Network Stats</h3>
      <div id="stats-container"></div>
    </div>
    <div class="sidebar-section">
      <h3>Top Bridges (Betweenness)</h3>
      <div id="top-bridges"></div>
    </div>
    <div class="sidebar-section">
      <h3>Communities</h3>
      <div id="community-list"></div>
    </div>
  </div>

  <div id="tooltip"></div>
</div>

<script>
const LAYERS = {layers_json};

const LAYER_DESCRIPTIONS = {{
  post_overlap: "Strong ties: edges connect submolts that share the same <b>posters</b>. Agents who post in a submolt are active community members — this layer shows genuine structural overlap.",
  comment_overlap: "Weak ties: edges connect submolts that share the same <b>commenters</b>. Commenting is a lighter signal — agents engaging across communities without posting. Source: observatory dataset.",
  engagement_overlap: "Combined: edges connect submolts sharing agents who either <b>posted or commented</b>. Union of strong and weak ties gives the fullest picture of cross-community overlap.",
  interaction_overlap: "Information flow: edges weighted by <b>cross-community comments</b> — agents from one submolt commenting on posts in another. Excludes broadcasters (10+ submolts). This captures actual conversation bridging, not just co-presence.",
  karma_overlap: "Influence-weighted overlap: edges connect submolts sharing members, weighted by agent <b>karma</b> (log-scaled). Tests whether community clusters are driven by influential agents or lurkers.",
  reply_overlap: "Reply flow: edges weighted by cross-community <b>threaded replies</b> (parent_id). Stronger signal than top-level comments — shows genuine conversation flow between communities.",
  temporal_overlap: "Temporal correlation: edges connect submolts with <b>synchronized posting patterns</b> (cosine similarity of hourly activity). Reveals coordinated bursts between communities that may share no members."
}};

// Build layer toggle buttons dynamically from available layers
const LAYER_DISPLAY_NAMES = {{
  post_overlap: "Posts", comment_overlap: "Comments", engagement_overlap: "Engagement",
  interaction_overlap: "Interactions", karma_overlap: "Karma", reply_overlap: "Replies",
  temporal_overlap: "Temporal"
}};
(function buildLayerButtons() {{
  const toggle = document.getElementById("layer-toggle");
  const layerNames = Object.keys(LAYERS);
  layerNames.forEach((name, i) => {{
    const btn = document.createElement("button");
    btn.className = "layer-btn" + (i === 0 ? " active" : "");
    btn.dataset.layer = name;
    btn.textContent = LAYER_DISPLAY_NAMES[name] || name.replace("_overlap", "").replace(/_/g, " ");
    btn.addEventListener("click", () => loadLayer(name));
    toggle.appendChild(btn);
  }});
}})();

const color = d3.scaleOrdinal(d3.schemeTableau10);
const svg = d3.select("#force-svg");
const mainEl = document.getElementById("main");
const getWidth = () => mainEl.clientWidth - 300;
const getHeight = () => mainEl.clientHeight;

const g = svg.append("g");
const zoomBehavior = d3.zoom()
  .scaleExtent([0.1, 8])
  .on("zoom", e => g.attr("transform", e.transform));
svg.call(zoomBehavior);

d3.select("#btn-zoom-in").on("click", () => svg.transition().call(zoomBehavior.scaleBy, 1.5));
d3.select("#btn-zoom-out").on("click", () => svg.transition().call(zoomBehavior.scaleBy, 0.67));
d3.select("#btn-reset").on("click", () => svg.transition().call(zoomBehavior.transform, d3.zoomIdentity));

const linkG = g.append("g").attr("class", "links");
const nodeG = g.append("g").attr("class", "nodes");
const tooltip = d3.select("#tooltip");

let currentLayer = "post_overlap";
let DATA = null;
let sim = null;
let linkEls = null;
let nodeGroups = null;
let highlighted = null;

function loadLayer(layerName) {{
  currentLayer = layerName;
  DATA = JSON.parse(JSON.stringify(LAYERS[layerName]));

  // Update layer toggle buttons
  document.querySelectorAll(".layer-btn").forEach(btn => {{
    btn.classList.toggle("active", btn.dataset.layer === layerName);
  }});

  // Update layer description
  document.getElementById("layer-description").innerHTML = LAYER_DESCRIPTIONS[layerName] || "";

  // Update topbar stats
  document.getElementById("stat-nodes").innerHTML = `<b>${{DATA.nodes.length}}</b> submolts`;
  document.getElementById("stat-edges").innerHTML = `<b>${{DATA.edges.length}}</b> edges`;

  // Kill existing simulation
  if (sim) sim.stop();
  highlighted = null;

  // Clear SVG groups
  linkG.selectAll("*").remove();
  nodeG.selectAll("*").remove();

  if (DATA.nodes.length === 0) {{
    updateSidebar();
    return;
  }}

  // Scales
  const maxAuthors = d3.max(DATA.nodes, d => d.author_count) || 1;
  const rScale = d3.scaleSqrt().domain([1, maxAuthors]).range([3, 30]);
  const maxJaccard = d3.max(DATA.edges, d => d.weight) || 1;
  const wScale = d3.scaleLinear().domain([0, maxJaccard]).range([0.5, 4]);

  // Force simulation
  sim = d3.forceSimulation(DATA.nodes)
    .force("link", d3.forceLink(DATA.edges).id(d => d.id).distance(80).strength(d => d.weight * 2))
    .force("charge", d3.forceManyBody().strength(-120))
    .force("center", d3.forceCenter(getWidth() / 2, getHeight() / 2))
    .force("collision", d3.forceCollide().radius(d => rScale(d.author_count) + 2))
    .alphaDecay(0.02);

  // Draw edges
  linkEls = linkG.selectAll("line").data(DATA.edges)
    .join("line")
    .attr("stroke", "#30363d")
    .attr("stroke-opacity", 0.4)
    .attr("stroke-width", d => wScale(d.weight));

  // Draw nodes
  nodeGroups = nodeG.selectAll("g").data(DATA.nodes)
    .join("g")
    .call(d3.drag()
      .on("start", (e, d) => {{ if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
      .on("drag", (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
      .on("end", (e, d) => {{ if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }})
    );

  nodeGroups.append("circle")
    .attr("class", "node-circle")
    .attr("r", d => rScale(d.author_count))
    .attr("fill", d => color(d.community))
    .attr("stroke", d => d3.color(color(d.community)).darker(0.5))
    .on("mouseover", showTooltip)
    .on("mousemove", moveTooltip)
    .on("mouseout", hideTooltip)
    .on("dblclick", highlightNeighbors);

  nodeGroups.append("text")
    .attr("class", "node-label")
    .text(d => d.id)
    .style("font-size", d => Math.max(8, Math.min(14, rScale(d.author_count))) + "px")
    .style("display", document.getElementById("toggle-labels").checked ? null : "none");

  sim.on("tick", () => {{
    linkEls
      .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    nodeGroups.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
  }});

  // Update sidebar and apply filters
  updateSidebar();
  applyFilters();

  // Reset zoom
  svg.transition().duration(300).call(zoomBehavior.transform, d3.zoomIdentity);
}}

// Tooltip
function showTooltip(e, d) {{
  const neighbors = DATA.edges
    .filter(l => l.source.id === d.id || l.target.id === d.id)
    .map(l => ({{
      name: l.source.id === d.id ? l.target.id : l.source.id,
      jaccard: l.weight,
      shared: l.shared_agents
    }}))
    .sort((a, b) => b.jaccard - a.jaccard)
    .slice(0, 5);

  const layerLabel = currentLayer.replace("_overlap", "");
  const LAYER_LABELS = {{
    post_overlap: {{ count: "Posters", edge: (n) => `J=${{n.jaccard.toFixed(3)}}, ${{n.shared}} shared` }},
    comment_overlap: {{ count: "Commenters", edge: (n) => `J=${{n.jaccard.toFixed(3)}}, ${{n.shared}} shared` }},
    engagement_overlap: {{ count: "Engaged agents", edge: (n) => `J=${{n.jaccard.toFixed(3)}}, ${{n.shared}} shared` }},
    interaction_overlap: {{ count: "Total interactions", edge: (n) => `${{n.shared}} interactions, w=${{n.jaccard.toFixed(4)}}` }},
    reply_overlap: {{ count: "Cross-replies", edge: (n) => `${{n.shared}} replies, w=${{n.jaccard.toFixed(4)}}` }},
    karma_overlap: {{ count: "Weighted karma", edge: (n) => `w=${{n.jaccard.toFixed(4)}}, ${{n.shared}} agents` }},
    temporal_overlap: {{ count: "Active hours", edge: (n) => `cosine=${{n.jaccard.toFixed(3)}}, ${{n.shared}} co-hours` }},
  }};
  const labels = LAYER_LABELS[currentLayer] || {{ count: "Agents", edge: (n) => `w=${{n.jaccard.toFixed(3)}}` }};
  const connHtml = neighbors.map(n =>
    `<div class="detail">${{n.name}} (${{labels.edge(n)}})</div>`
  ).join("");

  const countLabel = labels.count;
  tooltip.html(`
    <strong>${{d.id}}</strong><br>
    ${{countLabel}}: ${{d.author_count}}<br>
    Community: ${{d.community}}<br>
    Connections: ${{d.degree}}<br>
    Betweenness: ${{d.betweenness.toFixed(4)}}<br>
    <br><div class="detail"><b>Top overlaps:</b></div>
    ${{connHtml}}
  `).style("display", "block");
}}
function moveTooltip(e) {{
  tooltip.style("left", (e.pageX + 12) + "px").style("top", (e.pageY - 12) + "px");
}}
function hideTooltip() {{ tooltip.style("display", "none"); }}

// Double-click: highlight ego network
function highlightNeighbors(e, d) {{
  e.stopPropagation();
  if (highlighted === d.id) {{
    highlighted = null;
    nodeGroups.select("circle").attr("opacity", 1);
    nodeGroups.select("text").attr("opacity", 1);
    linkEls.attr("stroke-opacity", 0.4);
    return;
  }}
  highlighted = d.id;
  const neighborIds = new Set();
  DATA.edges.forEach(l => {{
    if (l.source.id === d.id) neighborIds.add(l.target.id);
    if (l.target.id === d.id) neighborIds.add(l.source.id);
  }});
  neighborIds.add(d.id);

  nodeGroups.select("circle").attr("opacity", n => neighborIds.has(n.id) ? 1 : 0.08);
  nodeGroups.select("text").attr("opacity", n => neighborIds.has(n.id) ? 1 : 0);
  linkEls.attr("stroke-opacity", l =>
    (l.source.id === d.id || l.target.id === d.id) ? 0.8 : 0.02);
}}
svg.on("click", () => {{
  if (highlighted) {{
    highlighted = null;
    nodeGroups.select("circle").attr("opacity", 1);
    nodeGroups.select("text").attr("opacity", 1);
    linkEls.attr("stroke-opacity", 0.4);
  }}
}});

// Filters
function applyFilters() {{
  if (!DATA || !nodeGroups || !linkEls) return;

  const minShared = +document.getElementById("filter-shared").value;
  const minAuthors = +document.getElementById("filter-authors").value;
  const minJaccard = +document.getElementById("filter-jaccard").value / 100;
  const search = document.getElementById("search-input").value.toLowerCase();

  document.getElementById("val-shared").textContent = minShared;
  document.getElementById("val-authors").textContent = minAuthors;
  document.getElementById("val-jaccard").textContent = minJaccard.toFixed(2);

  const visibleNodes = new Set();
  DATA.nodes.forEach(n => {{
    const matchSearch = !search || n.id.toLowerCase().includes(search);
    const matchAuthors = n.author_count >= minAuthors;
    if (matchSearch && matchAuthors) visibleNodes.add(n.id);
  }});

  linkEls
    .attr("display", d =>
      visibleNodes.has(d.source.id) && visibleNodes.has(d.target.id) &&
      d.shared_agents >= minShared && d.weight >= minJaccard
        ? null : "none")
    .attr("stroke-opacity", 0.4);

  nodeGroups.attr("display", d => visibleNodes.has(d.id) ? null : "none");

  // Update visible stats
  const visEdges = DATA.edges.filter(d =>
    visibleNodes.has(d.source.id) && visibleNodes.has(d.target.id) &&
    d.shared_agents >= minShared && d.weight >= minJaccard);
  document.getElementById("stats-container").innerHTML = `
    <div class="stat-row"><span>Visible nodes</span><span class="stat-val">${{visibleNodes.size}}</span></div>
    <div class="stat-row"><span>Visible edges</span><span class="stat-val">${{visEdges.length}}</span></div>
    <div class="stat-row"><span>Total nodes</span><span class="stat-val">${{DATA.nodes.length}}</span></div>
    <div class="stat-row"><span>Total edges</span><span class="stat-val">${{DATA.edges.length}}</span></div>
  `;
}}

function updateSidebar() {{
  if (!DATA || DATA.nodes.length === 0) {{
    document.getElementById("stats-container").innerHTML =
      `<div class="stat-row"><span>No data for this layer</span></div>`;
    document.getElementById("top-bridges").innerHTML = "";
    document.getElementById("community-list").innerHTML = "";
    return;
  }}

  // Top bridges
  const topBridges = [...DATA.nodes].sort((a, b) => b.betweenness - a.betweenness).slice(0, 20);
  const maxBet = topBridges[0]?.betweenness || 1;
  document.getElementById("top-bridges").innerHTML = topBridges.map(n => `
    <div class="top-item" data-id="${{n.id}}">
      <span class="swatch" style="background:${{color(n.community)}}"></span>
      <span class="name">${{n.id}}</span>
      <span style="color:var(--muted);font-size:11px">${{n.author_count}}</span>
      <span class="bar-wrap"><span class="bar" style="width:${{n.betweenness / maxBet * 100}}%"></span></span>
    </div>
  `).join("");

  // Communities
  const commMap = {{}};
  DATA.nodes.forEach(n => {{
    if (!commMap[n.community]) commMap[n.community] = [];
    commMap[n.community].push(n);
  }});
  const commList = Object.entries(commMap).sort((a, b) => b[1].length - a[1].length);
  document.getElementById("community-list").innerHTML = commList.map(([c, members]) => `
    <div class="community-row" data-community="${{c}}">
      <span class="swatch" style="background:${{color(c)}}"></span>
      <span>${{members.length}} submolts</span>
      <span style="color:var(--muted);font-size:11px;margin-left:auto">
        ${{members.sort((a,b) => b.author_count - a.author_count).slice(0,3).map(m => m.id).join(", ")}}
      </span>
    </div>
  `).join("");

  // Re-bind sidebar click handlers
  document.querySelectorAll(".top-item").forEach(el => {{
    el.addEventListener("click", () => {{
      const id = el.dataset.id;
      const node = DATA.nodes.find(n => n.id === id);
      if (node) highlightNeighbors({{stopPropagation:()=>{{}}}}, node);
    }});
  }});

  document.querySelectorAll(".community-row").forEach(el => {{
    el.addEventListener("click", () => {{
      const c = +el.dataset.community;
      const members = new Set(DATA.nodes.filter(n => n.community === c).map(n => n.id));
      nodeGroups.select("circle").attr("opacity", n => members.has(n.id) ? 1 : 0.08);
      nodeGroups.select("text").attr("opacity", n => members.has(n.id) ? 1 : 0);
      linkEls.attr("stroke-opacity", l =>
        members.has(l.source.id) && members.has(l.target.id) ? 0.8 : 0.02);
      highlighted = "community-" + c;
    }});
  }});
}}

// Filter event listeners
document.getElementById("filter-shared").addEventListener("input", applyFilters);
document.getElementById("filter-authors").addEventListener("input", applyFilters);
document.getElementById("filter-jaccard").addEventListener("input", applyFilters);
document.getElementById("search-input").addEventListener("input", applyFilters);

// Label toggle
document.getElementById("toggle-labels").addEventListener("change", function() {{
  if (nodeGroups) nodeGroups.selectAll(".node-label").style("display", this.checked ? null : "none");
}});

// Initial load — first available layer
loadLayer(Object.keys(LAYERS)[0]);
</script>
</body>
</html>"""


def main() -> None:
    layers = json.loads(Path(GRAPH_PATH).read_text())
    html = build_html(layers)
    out = Path(OUTPUT_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)

    print(f"Visualization -> {out}")
    for name, data in layers.items():
        print(f"  {name}: {len(data['nodes'])} nodes, {len(data['edges'])} edges")


if __name__ == "__main__":
    main()
