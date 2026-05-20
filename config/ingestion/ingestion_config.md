# Ingestion config reference

The ingestion layer is fully config-driven. Adding a new EDGAR endpoint or run requires only YAML changes — no Python code changes needed.

## File overview

| File | Purpose |
|---|---|
| `api.yaml` | EDGAR base URLs, request headers, rate limit |
| `bigquery.yaml` | GCP project, dataset, location, credentials file path |
| `checkpoints.yaml` | Local checkpoint directory and cleanup behaviour |
| `endpoints.yaml` | One entry per EDGAR endpoint — pure API descriptors |
| `runs.yaml` | Named presets — define params, destination table, and write mode |

All files are deep-merged into a single config dict at runtime. Any `${VAR}` token is substituted from the environment (`.env`). Dotted tokens like `${edgar.base_url}` are resolved from sibling config keys in the merged dict.

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

Endpoints are pure API descriptors. They define what to fetch and how to parse the raw response into rows. The BigQuery destination lives in `runs.yaml`, not here — so the same endpoint can be used by multiple runs writing to different tables.

```yaml
endpoints:
  - name: string              # unique identifier, used in runs.yaml as the endpoint value
    description: string       # shown in list-endpoints output
    url: string               # full URL; {param} tokens filled at runtime from run params
    method: GET               # only GET is supported today
    path_params:              # documents which {tokens} the URL contains
      - name: string
        description: string
```

Checkpoint files are saved under `checkpoints/{run_name}/` — the run name is used as the subdirectory so each preset's raw files are grouped together.

### BQ table schema

Each API response is stored as **one row**. Top-level keys from the JSON response become BQ columns; any value that is a list or dict is serialised to a JSON string (so BQ never creates REPEATED fields or deeply nested structs). Scalars are kept as their native types.

| Column pattern | BQ type | Content |
|---|---|---|
| Top-level scalar fields | Autodetected (`STRING`, `INTEGER`, etc.) | Native field values from the API response |
| Top-level list/dict fields | `STRING` | JSON-serialised nested value — query with `JSON_VALUE` / `JSON_EXTRACT_ARRAY` in dbt |
| `_ingested_at` | `STRING` | ISO 8601 UTC load timestamp |

---

## `runs.yaml` — field reference

Named presets for triggering ingestion from GitHub Actions or locally. Each run specifies its endpoint, parameters, destination BigQuery table, and write mode. The workflow reads this file at runtime — adding a preset here is all you need to expose it in CI.

```yaml
runs:
  <preset_name>:
    endpoint: string            # must match a name in endpoints.yaml
    bigquery_table: string      # destination table name (created automatically on first run)
    write_disposition: string   # WRITE_TRUNCATE | WRITE_APPEND
    schedule: true              # optional — run in the daily cron (06:00 UTC)
    schedule: quarterly         # optional — run in the quarterly cron (1st of Jan/Apr/Jul/Oct)
    cik: string | [string]      # path params — scalar or list
    taxonomy: string | [string]
    concept: string | [string]
    unit: string | [string]
    period: string | [string] | {from: string, to: string | CURRENT}
```

### `write_disposition`

| Value | Behaviour |
|---|---|
| `WRITE_TRUNCATE` | Replaces the entire table on every run. Use for reference snapshots (e.g. tickers). |
| `WRITE_APPEND` | Adds rows to the table. Use for time-series or per-company fact data. |

### Param types

| Type | Syntax | Behaviour |
|---|---|---|
| Scalar | `cik: "0000320193"` | Passed as-is to the endpoint |
| List | `cik: ["0000320193", "0000789019"]` | Iterates over each value; multiple list params produce the cartesian product |
| Period interval | `period: {from: CY2022Q1, to: CURRENT}` | Expands to a list of period strings; `CURRENT` resolves at runtime |

**CURRENT resolution** (based on today's date):

| Format | Resolves to |
|---|---|
| `CY{year}` (annual) | `CY{last_year}` — conservative, ensures full-year 10-K filings are available (~April) |
| `CY{year}Q{n}` (quarterly duration) | Last complete quarter minus a 45-day filing lag |
| `CY{year}Q{n}I` (quarterly instant) | Same as quarterly, with the `I` suffix |

### Period format for `xbrl_frames`

The EDGAR API distinguishes between two period types:

| Concept type | Example concepts | Period format | Example |
|---|---|---|---|
| Instant (balance sheet) | `Assets`, `Liabilities`, `StockholdersEquity` | `CY{year}Q{n}I` | `CY2023Q4I` |
| Duration (income statement) | `Revenues`, `NetIncomeLoss`, `OperatingExpenses` | `CY{year}` or `CY{year}Q{n}` | `CY2023`, `CY2023Q1` |

Using a duration period for an instant concept (or vice versa) returns a 404. The `from` period in an interval determines the format — `to` must match.

### Scheduling

```yaml
runs:
  daily_tickers:
    endpoint: company_tickers
    bigquery_table: raw_company_tickers
    write_disposition: WRITE_TRUNCATE
    schedule: true        # runs every day at 06:00 UTC

  all_company_facts:
    endpoint: company_facts
    bigquery_table: raw_company_facts
    write_disposition: WRITE_APPEND
    schedule: quarterly   # runs on the 1st of Jan, Apr, Jul, Oct
    cik:
      - "0000320193"
      - "0000789019"

  balance_sheet_snapshots:
    endpoint: xbrl_frames
    bigquery_table: raw_balance_sheet_snapshots
    write_disposition: WRITE_APPEND
    taxonomy: us-gaap
    unit: USD
    concept:
      - Assets
      - Liabilities
    period:
      from: CY2025Q1I
      to: CURRENT         # expands to every quarterly instant up to the latest available
```

### Using presets from the GitHub Actions UI

In **Actions → SEC EDGAR Ingestion → Run workflow**, enter the preset name in the `run_name` field. All params, table routing, and write mode are handled automatically by the ingestor.

---

## Adding a new endpoint and run

1. Open `endpoints.yaml` and append a new block:

```yaml
  - name: company_concept_bulk
    description: "Assets concept for a company across all periods"
    url: "${edgar.base_url}/api/xbrl/companyconcept/CIK{cik}/us-gaap/Assets.json"
    method: GET
    path_params:
      - name: cik
        description: "10-digit zero-padded CIK"
```

2. Add a run in `runs.yaml`:

```yaml
  assets_by_company:
    endpoint: company_concept_bulk
    bigquery_table: raw_assets_by_company
    write_disposition: WRITE_APPEND
    cik:
      - "0000320193"
      - "0000789019"
```

3. Run it:

```bash
python -m src.ingestion.ingestor run --preset assets_by_company
```

The table is created in BigQuery automatically on first run.

### Tips

- Use `${edgar.base_url}` for `https://data.sec.gov` endpoints and `${edgar.secondary_base_url}` for `https://www.sec.gov` endpoints rather than hardcoding the host.
- Use `WRITE_TRUNCATE` when you want a clean snapshot on every run (e.g. reference data). Use `WRITE_APPEND` for per-entity or per-period data you accumulate over time.
- Run `python -m src.ingestion.ingestor list-endpoints` at any time to see all registered endpoints and their required params.
- All endpoints write to the same two-column schema (`_data`, `_ingested_at`), so no BQ table setup is needed — tables are created automatically on first run.
