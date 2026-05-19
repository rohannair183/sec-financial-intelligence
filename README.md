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

### Usage

```bash
# activate the virtualenv
source .venv/bin/activate

# list all configured endpoints
python -m src.ingestion.ingestor list-endpoints

# ingest all company tickers
python -m src.ingestion.ingestor run --endpoint company_tickers

# ingest XBRL facts for Apple
python -m src.ingestion.ingestor run --endpoint company_facts --cik 0000320193

# ingest a specific concept across all companies for a period
python -m src.ingestion.ingestor run \
  --endpoint xbrl_frames \
  --taxonomy us-gaap \
  --concept Assets \
  --unit USD \
  --period CY2023
```

### Setup

```bash
# install dependencies
uv sync

# copy and fill in credentials
cp .env.example .env   # set DBT_KEYFILE, GCP_PROJECT, BQ_DATASET, EDGAR_USER_AGENT
```

---

## GitHub Actions

The workflow at `.github/workflows/ingest.yml` can run any ingestion endpoint from the GitHub UI or on a schedule.

### Triggering a run

Go to **Actions → SEC EDGAR Ingestion → Run workflow**. Pick an endpoint and fill in only the parameters that endpoint requires:

| Endpoint | Required inputs |
|---|---|
| `company_tickers` | _(none)_ |
| `company_submissions` | `cik` |
| `company_facts` | `cik` |
| `company_concept` | `cik`, `taxonomy`, `concept` |
| `xbrl_frames` | `taxonomy`, `concept`, `unit`, `period` |

The workflow also runs on a daily schedule (06:00 UTC) for `company_tickers`.

### Secrets to configure

Add these under **Settings → Secrets and variables → Actions → New repository secret**:

| Secret name | What to put in it |
|---|---|
| `GCP_SA_KEY` | The **full JSON content** of your GCP service account key file |
| `GCP_PROJECT` | Your GCP project ID (e.g. `sec-edgar-intelligence`) |
| `BQ_DATASET` | BigQuery dataset (e.g. `raw`) |
| `BQ_LOCATION` | BigQuery location (e.g. `US`) |
| `EDGAR_USER_AGENT` | Your SEC user-agent string (e.g. `Your Name your@email.com`) |

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
