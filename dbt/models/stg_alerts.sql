{{ config(materialized='view', copy_grants=true) }}

select
    alert_id,
    header,
    effect,
    service_effect,
    severity,
    captured_at_utc
from {{ source('transitpulse', 'alerts') }}