"""Orchestration layer and click CLI for the EDGAR ingestion pipeline."""

import sys
from pathlib import Path

import click

from src.utils.config import load_ingestion_config
from src.ingestion import client as _client_mod
from src.ingestion import checkpoint as _checkpoint_mod
from src.ingestion import loader as _loader_mod


class Ingestor:
    """Wires config, HTTP client, checkpoint store, and BigQuery loader."""

    def __init__(self, config_dir: str | Path = "config/ingestion"):
        self._cfg = load_ingestion_config(config_dir)
        self._client = _client_mod.EdgarClient(self._cfg)
        self._loader = _loader_mod.BigQueryLoader(self._cfg)
        self._endpoints = {ep["name"]: ep for ep in self._cfg.get("endpoints", [])}
        self._ckpt_cfg = self._cfg.get("checkpoints", {})

    def run(self, endpoint_name: str, **path_params: str) -> Path:
        """
        Fetch one endpoint, checkpoint locally, load to BigQuery, then clean up.
        Returns the checkpoint path (already deleted on success).
        Raises on any step failure so the caller can handle re-runs.
        """
        ep = self._endpoints.get(endpoint_name)
        if ep is None:
            raise ValueError(
                f"Unknown endpoint '{endpoint_name}'. "
                f"Available: {sorted(self._endpoints)}"
            )

        url = ep["url"].format(**path_params)
        click.echo(f"[fetch]      {url}")
        data = self._client.fetch(url)

        base_dir = self._ckpt_cfg.get("base_dir", "checkpoints")
        ckpt_path = _checkpoint_mod.save(
            base_dir=base_dir,
            subdir=ep["checkpoint_subdir"],
            endpoint=endpoint_name,
            params=path_params,
            data=data,
        )
        click.echo(f"[checkpoint] {ckpt_path}")

        bq = self._cfg["bigquery"]
        table = ep["bigquery_table"]
        disposition = ep.get("write_disposition", "WRITE_APPEND")
        row_transform = ep.get("row_transform")
        click.echo(f"[load]       {bq['project']}.{bq['dataset']}.{table}")
        self._loader.load(table, ckpt_path, disposition, row_transform=row_transform)

        if self._ckpt_cfg.get("delete_on_success", True):
            _checkpoint_mod.delete(ckpt_path)
            click.echo(f"[cleanup]    deleted {ckpt_path}")

        click.echo("[done]")
        return ckpt_path

    def endpoints(self) -> list[str]:
        """Return the names of all configured endpoints."""
        return sorted(self._endpoints)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """SEC EDGAR ingestion pipeline."""


@cli.command()
@click.option("--endpoint", required=True, help="Endpoint name from endpoints.yaml")
@click.option("--cik", default=None, help="10-digit zero-padded CIK")
@click.option("--taxonomy", default=None, help="XBRL taxonomy (e.g. us-gaap)")
@click.option("--concept", default=None, help="XBRL concept (e.g. Assets)")
@click.option("--unit", default=None, help="Unit of measure (e.g. USD)")
@click.option("--period", default=None, help="Reporting period (e.g. CY2023)")
@click.option("--config-dir", default="config/ingestion", show_default=True)
@click.pass_context
def run(ctx, endpoint, cik, taxonomy, concept, unit, period, config_dir):
    """Fetch one endpoint and load results into BigQuery."""
    path_params = {
        k: v
        for k, v in {
            "cik": cik,
            "taxonomy": taxonomy,
            "concept": concept,
            "unit": unit,
            "period": period,
        }.items()
        if v is not None
    }
    try:
        Ingestor(config_dir=config_dir).run(endpoint, **path_params)
    except (ValueError, RuntimeError, OSError) as exc:
        click.echo(f"[error] {exc}", err=True)
        ctx.exit(1)


@cli.command(name="list-endpoints")
@click.option("--config-dir", default="config/ingestion", show_default=True)
def list_endpoints(config_dir):
    """List all configured endpoints."""
    cfg = load_ingestion_config(config_dir)
    for ep in cfg.get("endpoints", []):
        params = ", ".join(p["name"] for p in ep.get("path_params") or [])
        click.echo(f"  {ep['name']:<22} {ep['description']}")
        if params:
            click.echo(f"  {'':22} params: {params}")


if __name__ == "__main__":
    cli()
