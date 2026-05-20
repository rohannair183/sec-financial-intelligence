"""Drop all tables in the configured BigQuery raw dataset."""

import argparse

from google.cloud import bigquery
from google.oauth2 import service_account

from src.utils.config import load_ingestion_config


def drop_all_tables(config_dir: str = "config/ingestion", dry_run: bool = False) -> None:
    cfg = load_ingestion_config(config_dir)
    bq_cfg = cfg["bigquery"]

    credentials = service_account.Credentials.from_service_account_file(
        bq_cfg["credentials_file"],
        scopes=["https://www.googleapis.com/auth/bigquery"],
    )
    client = bigquery.Client(
        project=bq_cfg["project"],
        credentials=credentials,
        location=bq_cfg.get("location", "US"),
    )

    dataset_ref = f"{bq_cfg['project']}.{bq_cfg['dataset']}"
    tables = list(client.list_tables(dataset_ref))

    if not tables:
        print(f"No tables in {dataset_ref}")
        return

    print(f"{'[dry-run] ' if dry_run else ''}Dropping {len(tables)} table(s) from {dataset_ref}:")
    for t in tables:
        print(f"  {t.table_id}")
        if not dry_run:
            client.delete_table(f"{dataset_ref}.{t.table_id}")

    if not dry_run:
        print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drop all tables in the raw BQ dataset")
    parser.add_argument("--dry-run", action="store_true", help="List tables without dropping them")
    parser.add_argument("--config-dir", default="config/ingestion")
    args = parser.parse_args()
    drop_all_tables(config_dir=args.config_dir, dry_run=args.dry_run)
