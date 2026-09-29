# TechPulse

> Technology, observed every day.

TechPulse is an autonomous technology intelligence archive. It observes selected parts of the technology ecosystem every day — vulnerabilities, known-exploited threats, software releases, open-source activity, and technology news — structures those observations, and publishes them as a dated, public historical record.

**Live site:** https://singhtanishq.github.io/TechPulse/

The system runs entirely on GitHub infrastructure with no required server, database, paid API, or always-on computer. GitHub Actions performs collection, processing, generation, and validation; GitHub Pages serves the resulting static site.

---

## How it works

```text
PUBLIC SOURCES
NVD · CISA KEV · GitHub API · RSS/Atom
        ↓
GITHUB ACTIONS
daily schedule / manual dispatch
        ↓
REPORTING DATE RESOLVER
scripts/reporting_date.py
one India calendar day per edition
        ↓
SOURCE COLLECTORS
scripts/sources/*
raw JSON, dated by reporting day
        ↓
PROCESSORS
scripts/processors/*
normalized datasets + source health
        ↓
DAILY SNAPSHOT
data/daily/YYYY-MM-DD.json
dated historical edition
        ↓
GENERATORS
scripts/generators/*
frontend JSON with deterministic output
        ↓
VALIDATION
scripts/validate.py
syntax + JSON + structure + integrity gates
        ↓
COMMIT
only when repository content meaningfully changes
        ↓
DEPLOY
GitHub Pages
static site
````

---

## Data sources

| Source                                                                   | What it provides                                                                                     | Attribution                                                                     |
| ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| [NVD](https://nvd.nist.gov/)                                             | CVEs published or modified for the collection window, CVSS information, descriptions, and references | Records identify `NVD` as the source and link to NVD where applicable           |
| [CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) | Known Exploited Vulnerabilities catalog data and reporting-day additions derived from `dateAdded`    | Records identify `CISA KEV` as the source                                       |
| [GitHub REST API](https://docs.github.com/en/rest)                       | Repository metadata and latest stable releases for the configured tracked repositories               | Records identify `GitHub` as the source and link to GitHub                      |
| RSS/Atom feeds                                                           | Technology and security headlines, links, excerpts, and publication information                      | Records retain the configured publisher/source and link to the original article |

TechPulse does not intentionally generate or fabricate source records. RSS content is stored as short excerpts with links rather than full articles.

---

## Reporting-date semantics (Asia/Kolkata)

TechPulse reporting dates are **India calendar days** using `Asia/Kolkata` (IST, UTC+05:30). The reporting model is documented in `scripts/config/snapshot.json` and resolved by `scripts/reporting_date.py`.

### Edition date and covered day

For reporting date `X`, the normal edition window covers the previous India calendar day:

```text
[X - 1 00:00 IST, X 00:00 IST)
```

The scheduled workflow runs at:

```text
18:30 UTC
=
00:00 IST
```

This makes the intended edition date the India calendar day that has just begun, rather than relying directly on the machine's local clock.

GitHub Actions scheduling may execute slightly earlier or later than the requested cron time. The reporting-date resolver therefore determines the intended reporting date independently of the runner's execution timestamp. Manual dispatch can also provide an explicit reporting date.

### Historical data

Files in `data/daily/` are dated snapshots. The pipeline is idempotent: reprocessing identical input produces identical output, while a changed snapshot is replaced with the newly generated content for that same reporting date.

This means historical files are stable with respect to identical inputs, but they are not technically immutable objects.

Snapshots created under an earlier reporting model retain their own recorded `window` information so that historical interpretation does not depend on today's date rules.

### RSS observation model

RSS/Atom sources are ephemeral. The technology processor therefore uses a documented publication lookback and records the collection-time observation context.

The current technology window uses a 48-hour publication lookback before the covered day so that items still observable when the feed is collected can be represented consistently.

### Frontend date model

The frontend mirrors the reporting model in `src/js/dates.js`:

* date-only values are treated as calendar dates rather than UTC instants;
* ISO timestamps without an explicit offset are interpreted as UTC;
* relative labels such as `Today`, `Yesterday`, and `N days ago` are computed in the browser against the current IST calendar date;
* future-dated editions are identified as future rather than incorrectly shown as current;
* relative labels are never frozen into the generated JSON.

---

## Data integrity rules

### No invented scores

An NVD record without CVSS data retains a missing/unscored state rather than being converted into a numeric zero or LOW severity.

NVD severity information and CISA KEV known-exploited status are treated as separate concepts.

### No fabricated growth

Open-source daily star growth is calculated only when a comparable observation exists for the immediately preceding reporting date. Otherwise growth is reported as unavailable (`n/a`).

### Deterministic output

Generated datasets use stable ordering and deterministic processing wherever source data permits it. Reprocessing identical inputs produces byte-identical generated output.

The pipeline therefore avoids unnecessary commits caused solely by generation-time timestamp churn.

### Idempotent collectors

Re-collecting a reporting date with identical records does not intentionally rewrite an unchanged raw collection. Existing collection metadata is preserved where appropriate.

### Honest source health

Each source reports a health state such as:

```text
success
partial
failed
empty
```

`empty` means a healthy source produced no usable records for its legitimate window. It is different from a source failure.

A failure in one source does not intentionally destroy usable records from other sources. The generated dataset exposes source health, and the frontend surfaces degraded collection as `PARTIAL` when applicable.

The pipeline exits successfully when at least one collector provides usable data and all subsequent processing and validation stages succeed. It exits with failure when a required processing/generation stage fails or when every collector fails.

---

## Repository layout

```text
.github/
  workflows/
    collect.yml        daily collection pipeline
    deploy.yml         GitHub Pages deployment

scripts/
  run_pipeline.py      one-command local pipeline
  reporting_date.py    resolves the IST reporting date
  validate.py          offline validation and integrity checks

  config/
    github.json        tracked repositories and GitHub settings
    rss.json           configured RSS/Atom feeds
    snapshot.json      reporting-date and snapshot semantics

  sources/
    nvd/               NVD collector
    cisa/              CISA KEV collector
    github/            GitHub collector
    rss/               RSS/Atom collector

  processors/
    security.py
    releases.py
    opensource.py
    tech.py
    daily.py
    history.py
    utils.py

  generators/
    site_data.py
    archive.py

data/
  security/nvd/        raw NVD collections
  security/cisa/       raw CISA KEV collections
  releases/            raw GitHub release collections
  opensource/          raw GitHub repository metadata
  tech/                raw RSS/Atom entries
  daily/               dated daily snapshots
  normalized/          derived intermediate datasets

generated/
  data.json            frontend dataset
  archive.json         archive dataset for the History page

src/
  static frontend
  HTML + CSS + vanilla JavaScript
  dark + light themes
  IST-aware date rendering

tests/
  offline unit tests
  failure-injection checks
  fixtures
```

`data/normalized/` is derived intermediate data and is not part of the committed historical record.

---

## Local usage

Requirements:

* Python 3.10+
* Python standard library only
* no package installation required for the pipeline

### Run the complete pipeline

This collects from live sources for the next pending reporting date:

```bash
python3 scripts/run_pipeline.py
```

### Run a specific reporting date

```bash
python3 scripts/run_pipeline.py --date 2026-09-28
```

The edition date is an IST reporting date; under the current model its normal covered day is the preceding India calendar day.

### Re-run processing and generation from existing raw data

```bash
python3 scripts/run_pipeline.py --skip-collect
```

### Offline validation

```bash
python3 scripts/validate.py
```

### Offline tests

```bash
python3 -m unittest discover -s tests -v
```

### Failure-injection checks

```bash
python3 tests/failure_injection.py
```

---

## GitHub collector authentication

The GitHub collector can operate without a token for small workloads and can also use an authentication token supplied through the environment.

Unauthenticated:

```bash
python3 scripts/sources/github/collect.py
```

Authenticated:

```bash
GITHUB_TOKEN=<your-token> python3 scripts/sources/github/collect.py
```

For GitHub Actions, the workflow provides the repository's GitHub Actions token to the collector.

API quotas and limits are imposed by GitHub and can change independently of TechPulse; the collector therefore handles rate-limit responses rather than relying on a permanently hard-coded quota assumption.

---

## Preview the site locally

Serve the repository root rather than `src/` so that the frontend can resolve the generated data files correctly:

```bash
python3 -m http.server 8000
```

Then open:

```text
http://127.0.0.1:8000/src/index.html
```

---

## Automation

### Collect

`.github/workflows/collect.yml` runs the collection pipeline on the configured daily schedule, on relevant repository changes, and through manual dispatch.

The pipeline:

```text
checkout
→ offline validation
→ tests
→ reporting-date resolution
→ NVD collection
→ CISA KEV collection
→ GitHub collection
→ RSS/Atom collection
→ processing
→ generation
→ validation
→ commit if content changed
```

The workflow also records the processed India reporting date and source health in the run summary.

Concurrency controls serialize collection runs so overlapping executions do not intentionally modify the archive simultaneously.

### Deploy

`.github/workflows/deploy.yml` prepares the static site for GitHub Pages and deploys it after a successful Collect workflow. It can also run for relevant frontend/workflow changes.

The deployment staging area contains:

```text
src/
generated/
```

and excludes development-only files such as the repository's tests, scripts, raw data collections, and Git metadata.

---

## Exit codes and failure behavior

### Exit `0`

The pipeline completed successfully.

A source may still be `partial` provided usable data remains available and all downstream processing, generation, and validation stages succeed.

### Exit `1`

The pipeline failed because:

* a processing stage failed;
* a generation stage failed;
* validation failed; or
* every collector failed, leaving no usable collection to process.

A failed Collect workflow prevents the normal successful-run deployment path from proceeding.

---

## Configuration

### `scripts/config/github.json`

Defines:

* tracked repositories;
* release collection limits;
* collection delay;
* stable-release inclusion rules.

Draft and prerelease releases are excluded by the current configuration.

### `scripts/config/rss.json`

Defines the configured RSS/Atom feeds and collection behavior.

Each feed is isolated so one unavailable feed does not automatically invalidate successful feeds.

### `scripts/config/snapshot.json`

Defines the reporting model, including:

* `Asia/Kolkata` reporting timezone;
* edition and covered-day semantics;
* daily snapshot directory conventions;
* source deduplication expectations;
* idempotency rules.

---

## Limitations

* External APIs and feeds can become unavailable, change response formats, impose rate limits, or temporarily return incomplete data.
* NVD collection is deliberately conservative and paginated to reduce request pressure. Authentication can be added later through an `NVD_API_KEY` secret if collection volume requires it.
* RSS/Atom feeds are ephemeral sources; older content can disappear or become unavailable to later collection runs.
* Open-source daily growth requires comparable observations for consecutive reporting dates. It is shown as `n/a` when that comparison is unavailable.
* The current GitHub collector tracks the repositories configured in `scripts/config/github.json`; the open-source view is not a universal ranking of all GitHub repositories.
* The first GitHub Pages deployment requires one-time Pages configuration with GitHub Actions as the deployment source. After that, deployment is automated by the workflow.

---

## License

MIT — see [LICENSE](LICENSE).

---

*TechPulse — building a dated record of technology change, one day at a time.*
