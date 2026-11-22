# TransitPulse

TransitPulse is a phased transit and weather data project focused on the Boston area.

## Releases

**Release 1 — Data platform:** Python, MBTA and Open-Meteo APIs, GCP, Airflow with Astro/Docker, Databricks with PySpark and Delta Lake, Snowflake, dbt browser IDE, Terraform, and GitHub Actions.

**Release 2 — Commuter app:** Next.js and FastAPI for live MBTA predictions and historical transit and weather analytics. Managed login can come later.

## Phase 1 — Local foundation

This phase prepares the repository and checks public API connectivity. It does not provision cloud resources, require credentials, or incur cloud charges.

### Ubuntu setup

From the repository root:

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The MBTA and Open-Meteo smoke checks will be added next. They use public endpoints and need outbound internet access.

## Repository layout

```text
airflow/dags/       Future Airflow workflows
dbt/                Future dbt project
infra/terraform/    Future infrastructure definitions
notebooks/          Future Databricks/PySpark notebooks
src/transitpulse/   Python pipeline package
tests/              Smoke and unit tests
```

## Safety and cost

- Keep `.env`, access keys, private keys, and Terraform state out of Git.
- No paid cloud service is configured or provisioned in Phase 1.
