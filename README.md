# Moltbook Network Graph

Visualize interaction networks between AI agents on [Moltbook](https://www.moltbook.com).

Scrapes posts and comments from the Moltbook API, builds a directed weighted interaction graph, and renders an interactive two-view visualization:
- **Chord diagram** — community-to-community interaction overview
- **Force-directed graph** — agent-level drill-down with filtering

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your Moltbook API key
```

## Usage

### Full pipeline (scrape + build + visualize)

```bash
python main.py run --api-key YOUR_KEY --mode submolts --out-dir ./output
```

Then open `output/index.html` in your browser.

### Individual steps

```bash
# Scrape all submolts
python main.py scrape --api-key YOUR_KEY --mode submolts --out data/interactions.json

# Scrape specific posts
python main.py scrape --api-key YOUR_KEY --mode posts --ids post1,post2,post3 --out data/interactions.json

# Build graph from interactions
python main.py build --input data/interactions.json --out data/graph.json

# Generate visualization
python main.py viz --input data/graph.json --out output/index.html
```

## API Key

The `--api-key` flag takes precedence. If omitted, it reads from the `MOLTBOOK_API_KEY` environment variable (loaded from `.env` via python-dotenv).

**Important:** Always use `www.moltbook.com` — omitting `www` causes a redirect that strips the Authorization header.

## Overlap Pipeline

Analyzes structural overlap between submolts using bipartite membership projection. All scripts run from the project root.

### Data Collection

```bash
# 1. Fetch submolt directory
python -m overlap.fetch_submolts

# 2. Fetch posting membership per submolt
python -m overlap.fetch_membership
```

### Build Overlap Layers

Each script adds its layer(s) to `data/overlap_graphs.json`:

```bash
# Post, comment, and engagement overlap (Jaccard similarity)
python -m overlap.build_overlap

# Cross-community comment interactions (cosine-normalized)
python -m overlap.build_interactions

# Threaded reply flow between communities
python -m overlap.build_reply_overlap

# Karma-weighted membership overlap
python -m overlap.build_karma_overlap

# Temporal posting pattern correlation (cosine similarity)
python -m overlap.build_temporal
```

### Visualize

```bash
python -m overlap.viz
# Open output/overlap.html
```

The visualization dynamically shows toggle buttons for all layers present in the data file.

### Layer Summary

| Layer | Signal | Weight | Source |
|-------|--------|--------|--------|
| `post_overlap` | Strong ties (posters) | Jaccard | membership.json |
| `comment_overlap` | Weak ties (commenters) | Jaccard | comment_membership.json |
| `engagement_overlap` | Combined (union) | Jaccard | both membership files |
| `interaction_overlap` | Cross-community comments | cosine-normalized count | observatory parquet |
| `reply_overlap` | Threaded reply flow | cosine-normalized count | observatory.db |
| `karma_overlap` | Influence-weighted overlap | karma-weighted Jaccard | membership.json + observatory.db |
| `temporal_overlap` | Synchronized posting bursts | cosine similarity | observatory.db |

## Tests

```bash
python -m pytest tests/ -v
```

## Visualization Features

- **Layer toggle**: switch between overlap layers (auto-generated from data)
- **Force-directed graph**: submolt-level network with community coloring
- **Filters**: min shared agents, min submolt size, min similarity, search
- **Interactions**: hover tooltips, double-click for ego network, community highlight
- **Sidebar**: network stats, top bridges by betweenness centrality, community breakdown
- **Controls**: zoom, reset view, toggle labels
