

  create or replace view `sec-edgar-intelligence`.`sec_dbt_dev`.`stg_company_tickers`
  OPTIONS()
  as -- One row per SEC-registered company. Source is a daily WRITE_TRUNCATE snapshot so no dedup needed.
select
    safe_cast(cik_str as int64)             as cik,
    upper(ticker)                           as ticker,
    title                                   as company_name,
    safe_cast(_ingested_at as timestamp)    as ingested_at
from `sec-edgar-intelligence`.`raw`.`raw_company_tickers`;

