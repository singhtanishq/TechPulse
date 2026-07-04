# TechPulse

> Technology, observed every day.

TechPulse is an autonomous technology intelligence archive. It observes the
technology ecosystem every day — vulnerabilities, known-exploited threats,
software releases, open-source activity and technology news — structures the
observations, and publishes them as a permanent, public, daily record.

**Live site:** https://singhtanishq.github.io/TechPulse/

The system runs entirely on GitHub infrastructure at ₹0 operating cost: no
laptop, no server, no paid API, no database. GitHub Actions collects and
publishes daily; GitHub Pages serves the site.

---

## How it works

```
PUBLIC SOURCES (NVD · CISA KEV · GitHub API · RSS/Atom)
        ↓   GitHub Actions — daily schedule 06:30 UTC
SOURCE COLLECTORS          scripts/sources/*        raw JSON, dated by snapshot day
        ↓
PROCESSORS                 scripts/processors/*     normalized datasets + source health
        ↓
DAILY SNAPSHOT             data/daily/YYYY-MM-DD.json   immutable archive record
        ↓
GENERATORS                 scripts/generators/*     frontend JSON (deterministic)
        ↓
VALIDATION                 scripts/validate.py      schema + integrity gates
        ↓
COMMIT (only if data meaningfully changed)
        ↓
DEPLOY                     GitHub Pages             static site
```

## Data sources

| Source | What it provides | Attribution |
|--------|------------------|-------------|
| [NVD](https://nvd.nist.gov/) | CVEs published/modified on the snapshot day, CVSS scores, descriptions, references | every record carries `source: "NVD"` and links to `nvd.nist.gov` |
| [CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) | Known Exploited Vulnerabilities catalog; daily delta derived from `dateAdded` | `source: "CISA KEV"` |
| [GitHub REST API](https://docs.github.com/en/rest) | Metadata + latest stable releases for the configured tracked repositories | `source: "GitHub"`, links to github.com |
| RSS/Atom feeds | Technology/security headlines (title, link, short excerpt, date) | `source: "<publisher>"`, links to the original article |

TechPulse does not generate, rewrite or fabricate any of this data. RSS content
is stored as short excerpts with links — never full articles.

## Snapshot semantics

- A snapshot covers exactly one **UTC calendar day**
  (`00:00:00Z`–`23:59:59.999Z`), recorded in
  `scripts/config/snapshot.json`.
- The default target is the **previous completed UTC day**; the schedule runs
  at 06:30 UTC to allow a buffer for source publication and processing lag.
- Historical snapshots in `data/daily/` are append-only: a snapshot is
  rewritten only when its actual content changes, never silently by a time
  churn.
- RSS is ephemeral, so the technology window applies a documented 48-hour
  lookback before the snapshot day (items published no later than the end of
  the snapshot day, still observable at collection time).

## Data integrity rules

- **No invented scores.** An NVD record without CVSS keeps
  `severity: null` / `cvss: null` and is displayed as *UNSCORED*, never as
  zero or LOW. NVD severity and CISA KEV "known exploited" status are kept
  conceptually separate.
- **No fabricated growth.** Open-source daily star growth is computed only
  when a previous dated observation exists; otherwise it is reported as
  unavailable (`n/a`).
- **Deterministic output.** Sorted keys, stable ordering, timestamps derived
  from source data. Reprocessing identical inputs produces byte-identical
  files, so commits happen only when data meaningfully changed.
- **Idempotent collectors.** Re-collecting a date with identical records does
  not rewrite the file (the original `collectedAt` is preserved).
- **Honest failure.** Every source reports `success` / `partial` / `failed` /
  `empty`. One failing source never destroys other sources' data; the UI
  shows a *PARTIAL* status when any source degraded.

## Repository layout

```
.github/workflows/
  collect.yml        daily collection pipeline (schedule + dispatch + push)
  deploy.yml         GitHub Pages deployment
scripts/
  run_pipeline.py    one-command local pipeline (collect → process → generate)
  validate.py        offline validation (syntax, JSON, schemas, placeholders)
  config/            tracked repositories, RSS feeds, snapshot semantics
  sources/           nvd/ · cisa/ · github/ · rss/ collectors
  processors/        security · releases · opensource · tech · daily · history
  generators/        site_data · archive
data/
  security/nvd/      raw NVD collections (committed)
  security/cisa/     raw CISA KEV snapshots (committed)
  releases/          raw GitHub releases (committed)
  opensource/        raw GitHub repository metadata (committed)
  tech/              raw RSS/Atom entries (committed)
  daily/             the historical archive (committed)
  normalized/        intermediate datasets (derived each run, not committed)
generated/
  data.json          frontend dataset
  archive.json       archive dataset for the History page
src/                 static frontend (HTML/CSS/vanilla JS, no framework)
tests/               offline unit + failure-injection tests with fixtures
```

## Local usage

Requirements: Python 3.10+ (standard library only — no packages to install).

```bash
# Complete pipeline for the previous UTC day (hits live APIs)
python3 scripts/run_pipeline.py

# Specific snapshot date
python3 scripts/run_pipeline.py --date 2026-09-17

# Re-run only processing/generation from existing raw data
python3 scripts/run_pipeline.py --skip-collect

# Offline validation (no network)
python3 scripts/validate.py

# Tests (offline, fixture-based)
python3 -m unittest discover -s tests -v
python3 tests/failure_injection.py
```

The GitHub collector is optional-token aware:

```bash
# Unauthenticated: 60 requests/hour (small repo lists only)
python3 scripts/sources/github/collect.py

# Authenticated: 5,000 requests/hour
GITHUB_TOKEN=<your-token> python3 scripts/sources/github/collect.py
```

To preview the site locally, serve the repository root (not `src/`) so the
frontend can find `generated/data.json`:

```bash
python3 -m http.server 8000
# open http://127.0.0.1:8000/src/index.html
```

## Automation

**Collect** (`.github/workflows/collect.yml`) runs at **06:30 UTC daily**,
on every push touching `scripts/`/`tests/`, and via manual dispatch (with an
optional `snapshot_date` input). It: checks out → validates → runs tests →
collects all four sources (NVD, CISA KEV, GitHub with the workflow
`GITHUB_TOKEN`, RSS) → processes → generates → validates → and commits only
when data meaningfully changed
(`TechPulse: daily snapshot YYYY-MM-DD`). Concurrency controls serialize
runs; overlapping schedules cannot corrupt the archive.

**Deploy** (`.github/workflows/deploy.yml`) assembles a staging directory
(`src/` at the root, `generated/` alongside), uploads it as a Pages artifact
and deploys. It runs on pushes touching `src/`/`generated/` and after every
successful Collect run.

## Exit codes and failure behavior

- Pipeline exit `0` — completed. Partial source availability is reported in
  logs and in the dataset's `sources` health block, and is surfaced in the UI
  ("PARTIAL").
- Pipeline exit `1` — a processing/generation stage failed, or **every**
  collector failed (no usable data; nothing is committed).
- A failed Collect run blocks the Deploy workflow (no deploying to hide a
  broken pipeline).

## Configuration

- `scripts/config/github.json` — tracked repositories and collection options
  (prereleases and drafts are excluded; documented in the file).
- `scripts/config/rss.json` — RSS/Atom feeds; each feed fails independently.
- `scripts/config/snapshot.json` — snapshot model documentation.

## Limitations

- NVD rate limits unauthenticated clients; the collector pages conservatively
  (6 s between requests, retries with backoff). A token can be added later
  via the `NVD_API_KEY` secret if volume grows.
- The first GitHub Pages deployment required a one-time manual enablement
  (Settings → Pages → Source: GitHub Actions); subsequent deploys are fully
  automated.
- Daily growth for open-source projects requires two consecutive daily
  observations; it displays `n/a` before that.

## License

MIT — see [LICENSE](LICENSE).

---

*TechPulse — building a permanent record of technology change, one day at a
time.*
