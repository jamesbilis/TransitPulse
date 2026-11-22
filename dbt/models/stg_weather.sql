{{ config(materialized='view') }}

select *
from {{ source('transitpulse', 'weather') }}