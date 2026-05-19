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
