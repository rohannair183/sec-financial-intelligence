# sec-financial-intelligence

Analytics engineering pipeline over SEC EDGAR's XBRL and filing metadata APIs, modeling multi-company financial metrics into BigQuery using dbt.

---

## Ingestion

The ingestion layer is config-driven: every EDGAR endpoint, its BigQuery destination, and how its response should be shaped are all declared in `config/ingestion/`. No code changes are needed to add or modify an endpoint.

### Config layout

```
config/ingestion/
  api.yaml          # EDGAR base URL, headers, rate limit (10 req/s)
  bigquery.yaml     # GCP project, dataset, location, credentials file
  checkpoints.yaml  # Local checkpoint directory + delete_on_success flag
  endpoints.yaml    # One entry per EDGAR endpoint
  runs.yaml         # Named presets for GitHub Actions and recurring schedules
```

All `${VAR}` tokens in the YAML files are resolved from `.env` at runtime. Cross-references like `${edgar.base_url}` are resolved from sibling config keys.

### How a run works

```
fetch → checkpoint → BigQuery load → cleanup
```

1. **Fetch** — `EdgarClient` calls the EDGAR API with the correct `User-Agent` header and a token-bucket rate limiter (max 10 req/s). Transient errors (429, 5xx) are retried with exponential backoff.
2. **Checkpoint** — the raw JSON response is written to `checkpoints/{subdir}/{endpoint}_{params}_{timestamp}.json` before any BigQuery interaction.
3. **Load** — `BigQueryLoader` reads the checkpoint file and streams rows into BigQuery using the service account key. Schema is autodetected on first load.
4. **Cleanup** — if the load succeeds, the checkpoint file is deleted. If it fails, the file is kept so the load can be retried without re-fetching from EDGAR.

### Adding endpoints

New EDGAR endpoints can be added by appending a block to `config/ingestion/endpoints.yaml` — no Python changes needed. See [config/ingestion/ingestion_config.md](config/ingestion/ingestion_config.md) for the full field reference and examples.

### Endpoints

| Name | Description | Params |
|---|---|---|
| `company_tickers` | All SEC-registered tickers and CIKs | — |
| `company_submissions` | Filing history and metadata for a company | `cik` |
| `company_facts` | All XBRL financial facts for a company | `cik` |
| `company_concept` | XBRL data for one concept for a company | `cik`, `taxonomy`, `concept` |
| `xbrl_frames` | Cross-company values for one concept in one period | `taxonomy`, `concept`, `unit`, `period` |

### Run presets

Named presets in `config/ingestion/runs.yaml` group an endpoint and its params into a single re-runnable unit. Presets support list params and period intervals — see [config/ingestion/ingestion_config.md](config/ingestion/ingestion_config.md) for the syntax.

| Preset | Endpoint | What it fetches |
|---|---|---|
| `daily_tickers` | `company_tickers` | Full ticker → CIK mapping (daily) |
| `all_company_submissions` | `company_submissions` | Filing metadata for 8 companies (quarterly) |
| `all_company_facts` | `company_facts` | All XBRL facts for 8 companies (quarterly) |
| `balance_sheet_snapshots` | `xbrl_frames` | Assets, Liabilities, Equity, Cash — every quarter from 2021Q1 to CURRENT |
| `income_statement_annual` | `xbrl_frames` | Revenue, Net Income, Gross Profit, Operating Income, R&D — annual 2021–CURRENT |
| `income_statement_quarterly` | `xbrl_frames` | Revenue, Net Income — quarterly 2022Q1–CURRENT |
| `cash_flow_annual` | `xbrl_frames` | Operating cash flow — annual 2021–CURRENT |

### Usage

```bash
# activate the virtualenv
source .venv/bin/activate

# list all configured endpoints
python -m src.ingestion.ingestor list-endpoints

# run a named preset (expands lists and period intervals automatically)
python -m src.ingestion.ingestor run --preset income_statement_quarterly

# run a single endpoint manually
python -m src.ingestion.ingestor run --endpoint company_tickers

# run with explicit params
python -m src.ingestion.ingestor run \
  --endpoint xbrl_frames \
  --taxonomy us-gaap \
  --concept Assets \
  --unit USD \
  --period CY2023Q4I
```

### List and interval params

Any param in a preset can be a list; the ingestor iterates over the cartesian product of all list params. A `period` param can be a `{from, to}` interval instead of an explicit value — `CURRENT` in `to` resolves at runtime to the latest period with data available in EDGAR.

```yaml
# 4 concepts × every quarterly instant from 2021Q1 to the latest available = many runs
balance_sheet_snapshots:
  endpoint: xbrl_frames
  taxonomy: us-gaap
  unit: USD
  concept:
    - Assets
    - Liabilities
  period:
    from: CY2021Q1I
    to: CURRENT
```

`CURRENT` resolution:
- Annual (`CY{year}`): resolves to `CY{last_year}` — conservative, ensures full-year filings are available
- Quarterly (`CY{year}Q{n}`): resolves to the last complete quarter minus a 45-day filing lag
- Instant (`CY{year}Q{n}I`): same as quarterly, with the `I` suffix

### Setup

```bash
# install dependencies
uv sync

# copy and fill in credentials
cp .env.example .env   # set DBT_KEYFILE, GCP_PROJECT, BQ_DATASET, EDGAR_USER_AGENT
```

---

## GitHub Actions

The workflow at `.github/workflows/ingest.yml` can run any ingestion endpoint from the GitHub UI or on a schedule. Presets and scheduled runs are declared in `config/ingestion/runs.yaml` — no workflow edits needed to add new recurring jobs.

### Triggering a run

Go to **Actions → SEC EDGAR Ingestion → Run workflow**. You have two options:

**Option 1 — named preset** (recommended): enter a preset name from `config/ingestion/runs.yaml` in the `run_name` field. All params are read from the YAML automatically.

**Option 2 — manual inputs**: leave `run_name` empty, pick an endpoint from the dropdown, and fill in the params that endpoint requires:

| Endpoint | Required inputs |
|---|---|
| `company_tickers` | _(none)_ |
| `company_submissions` | `cik` |
| `company_facts` | `cik` |
| `company_concept` | `cik`, `taxonomy`, `concept` |
| `xbrl_frames` | `taxonomy`, `concept`, `unit`, `period` |

### Scheduled runs

The workflow triggers daily at 06:00 UTC and runs every preset in `runs.yaml` that has `schedule: true`. To add a new recurring job, append a preset with `schedule: true` to `runs.yaml` — no changes to the workflow file needed.

### Secrets to configure

Add these under **Settings → Secrets and variables → Actions → New repository secret**:

| Secret name | What to put in it |
|---|---|
| `GCP_SA_KEY` | The **full JSON content** of your GCP service account key file |
| `GCP_PROJECT` | Your GCP project ID (e.g. `sec-edgar-intelligence`) |
| `BQ_DATASET` | BigQuery dataset (e.g. `raw`) |
| `EDGAR_USER_AGENT` | Your SEC user-agent string (e.g. `Your Name your@email.com`) |

> **Note:** `BQ_LOCATION` is intentionally not stored as a secret. GitHub Actions masks every occurrence of a secret's value in log output — storing `US` as a secret causes `USD` to appear as `***D` in logs. The location is hardcoded to `US` directly in the workflow.

### Local vs CI: how secrets differ

> **The key difference is `DBT_KEYFILE` / `GCP_SA_KEY`.**

**Locally**, you have a `.json` service account key file on disk. Your `.env` sets `DBT_KEYFILE` to its path:
```
DBT_KEYFILE=/path/to/sec-edgar-intelligence-abc123.json
```

**In GitHub Actions**, there is no persistent filesystem to store a key file. Instead:
1. The full JSON content of the key is stored as the `GCP_SA_KEY` repository secret.
2. The workflow writes it to a temp file at `/tmp/sa_key.json` at runtime.
3. `DBT_KEYFILE` is set to that temp path in the job's `env` block.

The temp file exists only for the duration of the job and is never uploaded as an artifact. The actual key file (`.json`) should never be committed to git — it is already excluded by `.gitignore`.
