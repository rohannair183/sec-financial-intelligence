-- One row per tracked company (latest quarterly fetch).
-- The facts column contains the full nested XBRL reporting history as JSON;
-- mart models unpack specific concepts from it.
select
    safe_cast(cik as int64)                 as cik,
    entityName                              as entity_name,
    facts,
    safe_cast(_ingested_at as timestamp)    as ingested_at
from `sec-edgar-intelligence`.`raw`.`raw_company_facts`
qualify row_number() over (
    partition by cik
    order by safe_cast(_ingested_at as timestamp) desc
) = 1