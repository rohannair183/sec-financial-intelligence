# Ingestion config reference

The ingestion layer is fully config-driven. Adding a new EDGAR endpoint means adding one block to `endpoints.yaml` — no Python changes required.

## File overview

| File | Purpose |
|---|---|
| `api.yaml` | EDGAR base URLs, request headers, rate limit |
| `bigquery.yaml` | GCP project, dataset, location, credentials file path |
| `checkpoints.yaml` | Local checkpoint directory and cleanup behaviour |
| `endpoints.yaml` | One entry per EDGAR endpoint to ingest |
| `runs.yaml` | Named presets for GitHub Actions dispatch and scheduled runs |

All four files are deep-merged into a single config dict at runtime. Any `${VAR}` token is substituted from the environment (`.env`). Dotted tokens like `${edgar.base_url}` are resolved from sibling config keys in the merged dict.

---

## `api.yaml`

```yaml
edgar:
  base_url: "https://data.sec.gov"
  secondary_base_url: "https://www.sec.gov"
  headers:
    User-Agent: "${EDGAR_USER_AGENT}"   # resolved from .env
    Accept-Encoding: "gzip, deflate"
  rate_limit:
    requests_per_second: 10             # SEC enforces a hard limit of 10
```

`requests_per_second` controls the token-bucket rate limiter in `EdgarClient`. Lowering it reduces the chance of 429s when running many endpoints in sequence.

---

## `bigquery.yaml`

```yaml
bigquery:
  project: "${GCP_PROJECT}"
  dataset: "${BQ_DATASET}"
  location: "${BQ_LOCATION}"
  credentials_file: "${DBT_KEYFILE}"    # path to GCP service account JSON
```

All four values come from `.env`. The loader uses autodetect schema on every load, so tables are created automatically on first run.

---

## `checkpoints.yaml`

```yaml
checkpoints:
  base_dir: "checkpoints"
  delete_on_success: true
```

`delete_on_success: true` removes the local JSON file after a successful BigQuery load. Set it to `false` during development if you want to inspect raw responses without re-fetching.

---

## `endpoints.yaml` — field reference

```yaml
endpoints:
  - name: string              # unique identifier, used as the --endpoint CLI arg
    description: string       # shown in list-endpoints output
    url: string               # full URL; {param} tokens filled at runtime from --flags
    method: GET               # only GET is supported today
    path_params:              # documents which {tokens} the URL contains
      - name: string
        description: string
    checkpoint_subdir: string # subdirectory under checkpoints/ for this endpoint's files
    bigquery_table: string    # destination table name (created automatically)
    write_disposition: string # WRITE_TRUNCATE | WRITE_APPEND
    row_transform: string     # optional — see "Response shapes" below
```

### `write_disposition`

| Value | Behaviour |
|---|---|
| `WRITE_TRUNCATE` | Replaces the entire table on every run. Use for snapshots (tickers, company metadata). |
| `WRITE_APPEND` | Adds rows to the table. Use for time-series or per-company fact data. |

### `row_transform`

EDGAR API responses are not always a flat list of rows. Use `row_transform` to tell the loader how to extract rows from the raw response before sending to BigQuery.

| Value | When to use | Example response shape |
|---|---|---|
| *(omitted)* | Response is already a list, or is a single object to store as one row | `[{...}, {...}]` or `{...}` |
| `dict_values` | Response is a dict keyed by a numeric index | `{"0": {...}, "1": {...}}` |

If you encounter a `Too many fields` error from BigQuery, the response is likely an indexed dict — add `row_transform: dict_values`.

---

## `runs.yaml`

Named presets for triggering ingestion from GitHub Actions. Each preset maps a name to a full set of CLI params. The workflow reads this file at runtime — adding a preset here is all you need to do to expose it in CI.

```yaml
runs:
  <preset_name>:
    endpoint: string          # must match a name in endpoints.yaml
    schedule: true/false      # optional — include in the daily cron run
    cik: string               # optional path params — include only what the endpoint needs
    taxonomy: string
    concept: string
    unit: string
    period: string
```

### Period format for `xbrl_frames`

The EDGAR API distinguishes between two period types:

| Concept type | Example concepts | Period format | Example |
|---|---|---|---|
| Instant (balance sheet) | `Assets`, `Liabilities`, `StockholdersEquity` | `CY{year}Q{n}I` | `CY2023Q4I` |
| Duration (income statement) | `Revenues`, `NetIncomeLoss`, `OperatingExpenses` | `CY{year}` or `CY{year}Q{n}` | `CY2023`, `CY2023Q1` |

Using a duration period for an instant concept (or vice versa) returns a 404.

### Using presets from the GitHub Actions UI

In **Actions → SEC EDGAR Ingestion → Run workflow**, enter the preset name in the `run_name` field. The workflow reads the YAML and builds the CLI args — no manual param entry needed.

### Adding a scheduled preset

Set `schedule: true` on any preset and it will be included in the daily 06:00 UTC cron run automatically. No changes to the workflow file are needed.

```yaml
runs:
  daily_assets_q4:
    endpoint: xbrl_frames
    taxonomy: us-gaap
    concept: Assets
    unit: USD
    period: CY2023Q4I
    schedule: true
```

---

## Adding a new endpoint

1. Open `endpoints.yaml` and append a new block:

```yaml
  - name: company_concept_bulk
    description: "Assets concept for a company across all periods"
    url: "${edgar.base_url}/api/xbrl/companyconcept/CIK{cik}/us-gaap/Assets.json"
    method: GET
    path_params:
      - name: cik
        description: "10-digit zero-padded CIK"
    checkpoint_subdir: "company_concept_bulk"
    bigquery_table: "raw_company_concept_bulk"
    write_disposition: WRITE_APPEND
```

2. Run it:

```bash
python -m src.ingestion.ingestor run --endpoint company_concept_bulk --cik 0000320193
```

That's it. The table is created in BigQuery automatically on first run.

### Tips

- Use `${edgar.base_url}` for `https://data.sec.gov` endpoints and `${edgar.secondary_base_url}` for `https://www.sec.gov` endpoints rather than hardcoding the host.
- Use `WRITE_TRUNCATE` when you want a clean snapshot on every run (e.g. reference data). Use `WRITE_APPEND` for per-entity or per-period data you accumulate over time.
- Keep `checkpoint_subdir` unique per endpoint so checkpoint files from different endpoints don't mix.
- Run `python -m src.ingestion.ingestor list-endpoints` at any time to see all registered endpoints and their required params.
