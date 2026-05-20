"""BigQuery loader: loads a local JSON checkpoint file into a BQ table."""

import json
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery
from google.oauth2 import service_account


def _flatten_toplevel(raw: object) -> dict:
    """
    Produce a single flat row from a raw API response.
    Every value is coerced to a string so BQ always gets a uniform STRING schema:
      - list / dict  → json.dumps
      - scalar       → str()
      - None         → None  (BQ null, compatible with NULLABLE STRING)
    """
    row = raw if isinstance(raw, dict) else {"_value": raw}
    return {
        k: json.dumps(v) if isinstance(v, (list, dict)) else (str(v) if v is not None else None)
        for k, v in row.items()
    }


def _string_schema(row: dict) -> list[bigquery.SchemaField]:
    """Build an explicit all-STRING NULLABLE schema from the keys of a row dict."""
    return [bigquery.SchemaField(k, "STRING", mode="NULLABLE") for k in row.keys()]


class BigQueryLoader:
    """Loads local JSON checkpoint files into BigQuery tables."""
    def __init__(self, config: dict):
        bq_cfg = config["bigquery"]
        self._project = bq_cfg["project"]
        self._dataset = bq_cfg["dataset"]
        self._location = bq_cfg.get("location", "US")

        credentials = service_account.Credentials.from_service_account_file(
            bq_cfg["credentials_file"],
            scopes=["https://www.googleapis.com/auth/bigquery"],
        )
        self._client = bigquery.Client(
            project=self._project,
            credentials=credentials,
            location=self._location,
        )

    def load(self, table: str, path: Path, write_disposition: str, row_transform: str | None = None) -> None:
        """
        Load a JSON checkpoint file into {dataset}.{table}.
        All values are stored as STRING. Schema is derived from the rows and provided
        explicitly so BQ never infers types — no TIMESTAMP promotions, no INTEGER
        coercions, no cross-company type conflicts.
        Raises on failure so the orchestrator can skip checkpoint deletion.
        """
        table_ref = f"{self._project}.{self._dataset}.{table}"

        with path.open() as f:
            raw = json.load(f)

        if row_transform == "dict_values":
            raw_rows = list(raw.values())
        else:
            raw_rows = [raw]

        ingested_at = datetime.now(timezone.utc).isoformat()
        rows = [{**_flatten_toplevel(r), "_ingested_at": ingested_at} for r in raw_rows]

        if not rows:
            return

        bq_write_disposition = getattr(bigquery.WriteDisposition, write_disposition)
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            autodetect=False,
            schema=_string_schema(rows[0]),
            write_disposition=bq_write_disposition,
            schema_update_options=(
                [
                    bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION,
                    bigquery.SchemaUpdateOption.ALLOW_FIELD_RELAXATION,
                ]
                if bq_write_disposition == bigquery.WriteDisposition.WRITE_APPEND
                else []
            ),
        )

        job = self._client.load_table_from_json(rows, table_ref, job_config=job_config)
        job.result()
