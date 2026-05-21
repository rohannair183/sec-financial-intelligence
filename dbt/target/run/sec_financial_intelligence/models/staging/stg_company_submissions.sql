

  create or replace view `sec-edgar-intelligence`.`sec_dbt_dev`.`stg_company_submissions`
  OPTIONS()
  as -- One row per tracked company (latest quarterly fetch).
-- tickers and exchanges are kept as JSON array strings for downstream parsing.
select
    cik,
    name                                                        as company_name,
    entityType                                                  as entity_type,
    sic,
    sicDescription                                              as sic_description,
    ein,
    fiscalYearEnd                                               as fiscal_year_end,
    stateOfIncorporation                                        as state_of_incorporation,
    stateOfIncorporationDescription                             as state_of_incorporation_description,
    category,
    phone,
    website,
    investorWebsite                                             as investor_website,
    tickers,
    exchanges,
    (insiderTransactionForOwnerExists = '1')                    as insider_transaction_for_owner,
    (insiderTransactionForIssuerExists = '1')                   as insider_transaction_for_issuer,
    safe_cast(_ingested_at as timestamp)                        as ingested_at
from `sec-edgar-intelligence`.`raw`.`raw_company_submissions`
qualify row_number() over (
    partition by cik
    order by safe_cast(_ingested_at as timestamp) desc
) = 1;

