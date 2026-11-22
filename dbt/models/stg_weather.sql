{{ config(materialized='view', copy_grants=true) }}

select *
from {{ source('transitpulse', 'weather') }}