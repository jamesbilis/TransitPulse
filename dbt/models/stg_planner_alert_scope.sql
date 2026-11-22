{{ config(materialized='view', copy_grants=true) }}

select
    snapshot.captured_at_utc,
    snapshot.alert_id,
    snapshot.attributes:header::varchar as header,
    snapshot.attributes:severity::integer as severity,
    entity.index as entity_index,
    entity.value:route::varchar as route_id,
    entity.value:stop::varchar as stop_id,
    entity.value:activities as activities,
    period.index as period_index,
    try_to_timestamp_tz(period.value:start::varchar) as active_from,
    try_to_timestamp_tz(period.value:end::varchar) as active_until
from {{ source('planner', 'alert_snapshots') }} snapshot,
lateral flatten(input => snapshot.attributes:informed_entity, outer => true) entity,
lateral flatten(input => snapshot.attributes:active_period, outer => true) period
