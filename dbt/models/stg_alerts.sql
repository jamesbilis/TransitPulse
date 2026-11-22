{{ config(materialized='view') }}

select
    alert_id,
    header,
    effect,
    service_effect,
    severity,
    captured_at_utc
from {{ source('transitpulse', 'alerts') }}