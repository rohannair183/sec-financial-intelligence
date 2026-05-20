"""BigQuery loader: loads a local JSON checkpoint file into a BQ table."""

import json
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery
from google.oauth2 import service_account


def _apply_transform(raw: object, row_transform: str | dict | None) -> list:
    """
    Convert a raw JSON response into a list of row dicts for BigQuery.

    row_transform may be:
      None / omitted   — response is already a list, or wrap single object in [obj]
      "dict_values"    — response is {index: row_obj, ...}; extract .values() as rows
      dict             — structured transform; see supported types below

    Structured transform types:
      type: transpose_columnar
        Converts a dict of parallel arrays {"col": [v1,v2,...], ...} into a list of
        row dicts. Useful when the API returns data in columnar (not row) format.

        path  (str)        — dot-separated path to navigate to the columnar dict,
                             e.g. "filings.recent". Omit or leave empty to use root.
        hoist (list|dict)  — fields from the root object to add to every row.
                             list form:  [field, ...]          — kept with original names
                             dict form:  {source: dest, ...}   — renamed on hoist
    """
    if row_transform is None or row_transform == "":
        return raw if isinstance(raw, list) else [raw]

    if isinstance(row_transform, str):
        if row_transform == "dict_values":
            return list(raw.values())
        raise ValueError(f"Unknown row_transform string: {row_transform!r}")

    if not isinstance(row_transform, dict):
        raise ValueError(f"row_transform must be a string or dict, got {type(row_transform).__name__}")

    transform_type = row_transform.get("type")

    if transform_type == "transpose_columnar":
        # Navigate to the columnar node
        node = raw
        for key in (row_transform.get("path") or "").split("."):
            if key:
                node = node[key]

        # Build the fields to hoist from the root onto every row
        hoist_cfg = row_transform.get("hoist") or []
        if isinstance(hoist_cfg, list):
            hoisted = {k: raw.get(k) for k in hoist_cfg}
        else:
            # dict: {source_field: dest_field}
            hoisted = {dest: raw.get(src) for src, dest in hoist_cfg.items()}

        if not node:
            return []

        keys = list(node.keys())
        return [
            {**hoisted, **dict(zip(keys, values))}
            for values in zip(*[node[k] for k in keys])
        ]

    if transform_type == "flatten_xbrl_facts":
        # Flatten: facts → {taxonomy} → {concept} → units → {unit} → [entries]
        # Hoists cik and entityName from root; adds taxonomy, concept, unit, label, description per row.
        rows = []
        cik = raw.get("cik")
        entity_name = raw.get("entityName")
        for taxonomy, concepts in (raw.get("facts") or {}).items():
            for concept, concept_data in concepts.items():
                label = concept_data.get("label")
                description = concept_data.get("description")
                for unit, entries in (concept_data.get("units") or {}).items():
                    for entry in entries:
                        rows.append({
                            "cik": cik,
                            "entity_name": entity_name,
                            "taxonomy": taxonomy,
                            "concept": concept,
                            "unit": unit,
                            "label": label,
                            "description": description,
                            **entry,
                        })
        return rows

    raise ValueError(f"Unknown row_transform type: {transform_type!r}")


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

    def load(self, table: str, path: Path, write_disposition: str, row_transform: str | dict | None = None) -> None:
        """
        Load a JSON checkpoint file into {dataset}.{table}.
        Raises on failure so the orchestrator can skip checkpoint deletion.
        """
        table_ref = f"{self._project}.{self._dataset}.{table}"

        bq_write_disposition = getattr(bigquery.WriteDisposition, write_disposition)
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            autodetect=True,
            write_disposition=bq_write_disposition,
            schema_update_options=(
                [bigquery.SchemaUpdateOption.ALLOW_FIELD_RELAXATION]
                if bq_write_disposition == bigquery.WriteDisposition.WRITE_APPEND
                else []
            ),
        )

        with path.open() as f:
            raw = json.load(f)

        ingested_at = datetime.now(timezone.utc).isoformat()
        rows = [
            {**row, "_ingested_at": ingested_at}
            for row in _apply_transform(raw, row_transform)
        ]

        job = self._client.load_table_from_json(rows, table_ref, job_config=job_config)
        job.result()  # blocks until complete; raises google.api_core.exceptions on failure
