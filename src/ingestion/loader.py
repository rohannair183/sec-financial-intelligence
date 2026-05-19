"""BigQuery loader: loads a local JSON checkpoint file into a BQ table."""

import json
from pathlib import Path

from google.cloud import bigquery
from google.oauth2 import service_account


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
        Raises on failure so the orchestrator can skip checkpoint deletion.

        row_transform options:
          None         — list as-is; wrap single object in a list
          "dict_values" — response is {index: row_obj, ...}; extract values as rows
        """
        table_ref = f"{self._project}.{self._dataset}.{table}"

        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            autodetect=True,
            write_disposition=getattr(bigquery.WriteDisposition, write_disposition),
        )

        with path.open() as f:
            raw = json.load(f)

        if row_transform == "dict_values":
            rows = list(raw.values())
        elif isinstance(raw, list):
            rows = raw
        else:
            rows = [raw]

        job = self._client.load_table_from_json(rows, table_ref, job_config=job_config)
        job.result()  # blocks until complete; raises google.api_core.exceptions on failure
