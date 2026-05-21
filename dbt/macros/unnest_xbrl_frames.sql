{#
  Unnests a raw xbrl_frames table into one row per (concept, period, company).
  All raw xbrl_frames tables share the same schema:
    taxonomy, tag, ccp, uom, label, description, pts (STRING), data (JSON array), _ingested_at (STRING)
  Each element of data has: accn, cik, entityName, loc, end, val.

  Deduplicates by (tag, ccp) keeping the latest ingestion run before unnesting.
#}
{% macro unnest_xbrl_frames(source_name, table_name) %}

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
    from {{ source(source_name, table_name) }}
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

{% endmacro %}
