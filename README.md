# TechPulse

> Technology, observed every day.

TechPulse is an autonomous technology intelligence and historical archive. It continuously collects, processes, and publishes structured data about technology changes — vulnerabilities, software releases, open-source activity, and technology news — creating a permanent public record of the technology ecosystem.

## Architecture

```
PUBLIC SOURCES
      ↓
SOURCE ADAPTERS
      ↓
RAW / NORMALIZED DATA
      ↓
PROCESSORS
      ↓
DAILY SNAPSHOT GENERATION
      ↓
GENERATED STATIC JSON
      ↓
STATIC FRONTEND (GitHub Pages)
      ↓
GITHUB ACTIONS (scheduled)
```

## Data Sources

| Source | Purpose | Collector |
|--------|---------|-----------|
| **NVD** | CVE vulnerabilities, CVSS scores, descriptions | `scripts/sources/nvd/collect.py` |
| **CISA KEV** | Known exploited vulnerabilities catalog | `scripts/sources/cisa/collect.py` |
| **GitHub API** | Repository metadata, releases, stars | `scripts/sources/github/collect.py` |
| **RSS/Atom** | Technology news from major publications | `scripts/sources/rss/collect.py` |

## Directory Structure

```
TechPulse/
├── .github/workflows/     # GitHub Actions (to be configured)
├── data/
│   ├── daily/             # Daily snapshots (historical archive)
│   ├── normalized/        # Processed, normalized data
│   ├── security/
│   │   ├── nvd/           # Raw NVD collections
│   │   └── cisa/          # Raw CISA KEV collections
│   ├── releases/          # Raw GitHub releases
│   ├── opensource/        # Raw GitHub repo metadata
│   └── tech/              # Raw RSS/Atom entries
├── generated/
│   ├── data.json          # Main frontend data
│   └── archive.json       # Historical archive data
├── scripts/
│   ├── config/            # Source configurations
│   │   ├── snapshot.json  # Snapshot semantics
│   │   ├── github.json    # Tracked repositories
│   │   └── rss.json       # RSS feed URLs
│   ├── sources/           # Source collectors
│   │   ├── nvd/
│   │   ├── cisa/
│   │   ├── github/
│   │   └── rss/
│   ├── processors/        # Data processors
│   │   ├── security.py
│   │   ├── releases.py
│   │   ├── opensource.py
│   │   ├── tech.py
│   │   ├── daily.py
│   │   └── history.py
│   ├── generators/        # Frontend data generators
│   │   ├── site_data.py
│   │   └── archive.py
│   └── run_pipeline.py    # Complete pipeline runner
├── src/
│   ├── index.html         # Home page
│   ├── security.html      # Security observatory
│   ├── releases.html      # Software releases
│   ├── opensource.html    # Open source activity
│   ├── history.html       # Historical archive
│   ├── css/
│   │   ├── base.css       # Design tokens & reset
│   │   ├── layout.css     # Layout components
│   │   └── components.css # UI components
│   └── js/
│       ├── data.js        # Data loader (fetch from generated/)
│       ├── app.js         # Main application logic
│       └── components.js  # Reusable UI components
├── .gitignore
├── LICENSE
└── README.md
```

## Daily Snapshot Semantics

TechPulse uses **UTC calendar day** model:

- Each snapshot represents a single UTC day (00:00:00Z – 23:59:59Z)
- Collection runs after the UTC day ends (recommended: 02:00 UTC)
- This ensures complete capture of that day's publications/modifications
- Snapshots are immutable once written to `data/daily/YYYY-MM-DD.json`

## Local Development

### Prerequisites

- Python 3.10+
- No external Python dependencies (standard library only)

### Quick Start

```bash
# Clone and enter
git clone https://github.com/singhtanishq/TechPulse
cd TechPulse

# Run complete pipeline (collects from live APIs)
python3 scripts/run_pipeline.py

# Or run individual stages
python3 scripts/sources/nvd/collect.py --hours 24
python3 scripts/sources/cisa/collect.py
python3 scripts/sources/github/collect.py
python3 scripts/sources/rss/collect.py

python3 scripts/processors/security.py
python3 scripts/processors/releases.py
python3 scripts/processors/opensource.py
python3 scripts/processors/tech.py
python3 scripts/processors/daily.py
python3 scripts/processors/history.py

python3 scripts/generators/site_data.py
python3 scripts/generators/archive.py
```

### Preview Frontend

```bash
# Using VS Code Live Server or any static server
# Serve the src/ directory
# Open http://localhost:5500/src/index.html
```

### Pipeline Options

```bash
# Run for specific date (UTC)
python3 scripts/run_pipeline.py --date 2026-09-17

# Skip collection (use existing raw data)
python3 scripts/run_pipeline.py --skip-collect

# Skip processing
python3 scripts/run_pipeline.py --skip-process

# Skip generation
python3 scripts/run_pipeline.py --skip-generate

# Run only one phase
python3 scripts/run_pipeline.py --only collect
python3 scripts/run_pipeline.py --only process
python3 scripts/run_pipeline.py --only generate
```

## Configuration

### Tracked Repositories

Edit `scripts/config/github.json` to modify the list of tracked GitHub repositories.

### RSS Feeds

Edit `scripts/config/rss.json` to add/remove RSS/Atom feeds.

### Snapshot Settings

Edit `scripts/config/snapshot.json` for snapshot semantics (advanced).

## GitHub Actions Automation

The pipeline is designed to run in GitHub Actions. A workflow should:

1. Checkout repository
2. Set up Python 3.11+
3. Run `python3 scripts/run_pipeline.py`
4. Detect meaningful changes in `generated/` and `data/daily/`
5. Commit and push changes
6. Deploy to GitHub Pages

**Not yet configured** — will be set up manually after local validation.

## Zero-Cost Philosophy

- **No paid APIs**: Uses public NVD, CISA, GitHub (unauthenticated), and RSS feeds
- **No paid infrastructure**: GitHub Actions (free for public repos) + GitHub Pages
- **No databases**: JSON files as storage
- **No cloud servers**: Fully static frontend
- **Minimal dependencies**: Python stdlib, vanilla HTML/CSS/JS

## Data Integrity

- **Deterministic output**: Sorted keys, stable ordering
- **Idempotent**: Re-running produces identical results
- **Source attribution**: Every record preserves `source` field
- **No fabricated data**: Empty states shown when data unavailable
- **Immutable history**: Daily snapshots never overwritten

## Frontend

Static HTML/CSS/JS with:
- Responsive design (mobile-first)
- No framework dependencies
- Vanilla ES6 modules
- Fetch-based data loading from `generated/data.json`
- Graceful empty states

## License

MIT License — see [LICENSE](LICENSE)

## Contributing

1. Fork the repository
2. Make changes locally
3. Run full pipeline: `python3 scripts/run_pipeline.py`
4. Verify frontend loads with real data
5. Submit PR with meaningful commit messages

## Status

**Current Phase**: Pre-automation implementation complete
- ✅ All source collectors implemented
- ✅ All processors implemented
- ✅ All generators implemented
- ✅ Frontend connected to generated data
- ✅ Placeholder data removed
- ✅ Local pipeline tested
- ⏳ GitHub Actions / Pages setup (manual step remaining)

---

*TechPulse — Building a permanent record of technology change, one day at a time.*