select alert_id, captured_at_utc
from {{ ref('stg_alerts') }}
group by alert_id, captured_at_utc
having count(*) > 1