

  create or replace view `sec-edgar-intelligence`.`sec_dbt_dev`.`stg_entity_public_float`
  OPTIONS()
  as -- Concept: EntityPublicFloat — annual, DEI taxonomy.


with latest_fetch as (
    select
        taxonomy,
        tag,
        ccp,
        uom,
        label,
        description,
        safe_cast(pts as int64)                     as pts,
        data,
        safe_cast(_ingested_at as timestamp)        as ingested_at
    from `sec-edgar-intelligence`.`raw`.`raw_entity_public_float`
    qualify row_number() over (
        partition by tag, ccp
        order by safe_cast(_ingested_at as timestamp) desc
    ) = 1
)

select
    taxonomy,
    tag                                             as concept,
    ccp                                             as calendar_period,
    uom                                             as unit,
    label,
    description,
    pts                                             as reporting_entity_count,
    json_value(item, '$.accn')                      as accession_number,
    safe_cast(json_value(item, '$.cik') as int64)   as cik,
    json_value(item, '$.entityName')                as entity_name,
    json_value(item, '$.loc')                       as location,
    safe_cast(json_value(item, '$.end') as date)    as period_end,
    safe_cast(json_value(item, '$.val') as numeric) as value,
    ingested_at
from latest_fetch
cross join unnest(json_extract_array(data)) as item

;

