# PM Dashboard

Local single-user portfolio dashboard for seven projects, built around direct `.mpp` ingestion, schedule variance visibility, action tracking, and an exception-first operating model.

## Stack

- Python 3.12
- FastAPI
- Jinja templates
- SQLite
- Java 17 + Maven for the MPXJ `.mpp` parser bridge

## Quick Start

1. Install Python dependencies:

```bash
python3 -m pip install --user -e .[dev]
```

2. Build the Java parser bridge:

```bash
cd tools/mpp-parser
mvn -q package
```

3. Run the sample import:

```bash
PYTHONPATH=src python3 -m pm_dashboard.ingest \
  --project pyrolysis-petal-2026 \
  --file "2026 Pyrolysis Petal - 24 Mar 2026.mpp"
```

4. Start the app:

```bash
PYTHONPATH=src python3 -m uvicorn pm_dashboard.main:app --reload
```

Open `http://127.0.0.1:8000`.

## What Phase 1 Includes

- Portfolio overview across seven seeded projects
- Direct `.mpp` upload and snapshot-based schedule variance detection
- Project drilldowns with milestones, critical tasks, and slipped tasks
- Attention queue for material slips, overdue actions, and stale plans
- Manual action tracking inside the dashboard
- Import history and error visibility

## Seeded Projects

The database is seeded with seven project records:

1. `pyrolysis-petal-2026`
2. `project-2`
3. `project-3`
4. `project-4`
5. `project-5`
6. `project-6`
7. `project-7`

The included sample `.mpp` file maps cleanly to `pyrolysis-petal-2026`.
