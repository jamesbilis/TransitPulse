{{ config(materialized='view', copy_grants=true) }}

with events as (
    select
        *,
        dateadd(
            second,
            scheduled_arrival_seconds - 43200,
            convert_timezone(
                'America/New_York', 'UTC', dateadd(hour, 12, service_date::timestamp_ntz)
            )
        ) as scheduled_arrival_utc,
        to_timestamp_ntz(observed_stop_epoch) as observed_arrival_utc
    from {{ source('planner', 'stop_events') }}
)
select
    events.*,
    versions.feed_version,
    datediff(second, scheduled_arrival_utc, observed_arrival_utc) as arrival_delay_seconds
from events
left join {{ source('planner', 'gtfs_versions') }} versions
    on events.service_date between versions.active_date and versions.end_date
qualify row_number() over (
    partition by service_date, trip_id, stop_id, stop_sequence
    order by versions.active_date desc nulls last, versions.feed_version desc
) = 1
