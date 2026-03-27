# PM Dashboard

Local single-user portfolio dashboard for project portfolios, built around direct `.mpp` ingestion, schedule variance visibility, weekly operating cadence, and an exception-first PM workflow.

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
python3 -m pm_dashboard.ingest \
  --project p2c \
  --file "2026 Pyrolysis Petal - 24 Mar 2026.mpp"
```

To import every recognized `.mpp` file in the repository root:

```bash
python3 -m pm_dashboard.ingest --all-repo-mpp
```

4. Start the app:

```bash
python3 -m uvicorn pm_dashboard.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Configuration

Primary environment variables:

- `PM_DASH_DATA_DIR`: persistent data directory (default: `./data`)
- `PM_DASH_DB_PATH`: SQLite database path (default: `<PM_DASH_DATA_DIR>/pm_dashboard.db`)
- `PM_DASH_EDITOR_USERNAME`: optional HTTP Basic username for editor access
- `PM_DASH_EDITOR_PASSWORD`: optional HTTP Basic password for editor access
- `PM_DASH_VIEWER_USERNAME`: optional HTTP Basic username for view-only access
- `PM_DASH_VIEWER_PASSWORD`: optional HTTP Basic password for view-only access
- `PM_DASH_AUTH_USERNAME`: legacy fallback for editor username
- `PM_DASH_AUTH_PASSWORD`: legacy fallback for editor password

Authentication is disabled unless at least one complete credential pair is set. Viewer credentials can browse all read-only pages and GET APIs, while editor credentials are required for uploads and all write actions.

## Current Feature Set

- Portfolio overview across all saved projects
- Direct `.mpp` upload and snapshot-based schedule variance detection
- Uploaded project files are stored in SQLite so the latest file stays loaded for both viewer and editor sessions
- Project drilldowns with milestones, critical tasks, slipped tasks, risks, decisions, and actions
- Weekly project workflow pages with weekly updates and suggestion review
- Weekly cockpit with review queue, portfolio signals, and executive summary draft/final sections
- Attention queue for material slips, overdue actions, stale plans, blocked cross-project dependencies, and leadership surprise risk
- Cross-project dependency detection from imported predecessor references plus a dedicated dependencies page
- Resource conflict detection across critical work on different projects
- Leadership surprise indicator with top drivers shown in the portfolio
- Health trend scoring/history for deteriorating or improving projects
- Manual action, risk, and decision tracking inside the dashboard
- Import history and parser error visibility

## Main Pages

- `/`: portfolio overview with attention ranking, leadership surprise drivers, and resource conflict clusters
- `/cockpit`: weekly PM cockpit with project-by-project update status and executive summary draft/final state
- `/attention`: consolidated queue of items that need PM intervention
- `/dependencies`: cross-project dependency register and overdue dependency view
- `/projects/{project_id}`: project detail page
- `/projects/{project_id}/workflow`: weekly workflow page for updates and suggestions
- `/admin/imports`: upload/import page and import history

## API Surface

- `GET /api/projects`: portfolio summaries
- `GET /api/projects/{project_id}`: project detail payload
- `GET /api/cockpit`: weekly cockpit data
- `GET /api/dependencies`: portfolio dependency register, optionally filtered by `project_id`
- `GET /api/portfolio/resource-conflicts`: cross-project resource conflict clusters
- `POST /api/projects/{project_id}/actions`: create an action
- `PATCH /api/actions/{action_id}`: update action status
- `POST /api/projects/{project_id}/weekly-updates`: create or upsert a weekly update
- `PATCH /api/weekly-updates/{update_id}`: edit a weekly update
- `GET /api/projects/{project_id}/suggestions`: list workflow suggestions
- `POST /api/suggestions/{suggestion_id}/accept`: accept a suggestion
- `POST /api/suggestions/{suggestion_id}/dismiss`: dismiss a suggestion
- `POST /api/projects/{project_id}/risks`: create a risk
- `PATCH /api/risks/{risk_id}`: update a risk
- `POST /api/projects/{project_id}/decisions`: create a decision
- `PATCH /api/decisions/{decision_id}`: update a decision
- `POST /api/imports/mpp`: upload and import an `.mpp` file
- `POST /api/portfolio/executive-summary/generate`: create the current week executive summary draft
- `POST /api/portfolio/executive-summary/{draft_id}/accept`: mark a draft accepted with optional PM-edited final payload
- `POST /api/portfolio/executive-summary/{draft_id}/dismiss`: dismiss a pending draft

## Data Model Notes

- Each `.mpp` import creates a new schedule snapshot for a project.
- Milestone variance and material slips are computed by comparing the latest snapshot with the previous snapshot.
- Imported tasks can carry `resource_names`, `primary_owner`, and `resource_key`, which feed the resource-conflict view.
- Imported predecessor references like `atlas:UP-45` create cross-project dependency records.
- Weekly updates, risks, decisions, and suggestions are persisted separately from schedule snapshots so the PM workflow stays editable between imports.

## Executive Summary Flow

1. Open the weekly cockpit for a target week.
2. Call `POST /api/portfolio/executive-summary/generate` or use the UI path that triggers it.
3. Review the generated draft, then accept it with optional PM edits through `POST /api/portfolio/executive-summary/{draft_id}/accept`.
4. The cockpit shows both the latest pending draft and the latest accepted final summary for that week.

## Project Setup

- Projects are created through the UI/API or on first import when a filename can be matched to a project key.
- Uploaded `.mpp` files are saved in the database as the current file for their project.
- Viewer and editor accounts read the same saved project files and project state; editor access only adds write actions.

## Railway Deployment

This repo includes a production `Dockerfile` for Railway. The lowest-cost deployment shape is:

- 1 Railway web service
- 1 persistent volume mounted at `/data`
- SQLite stored on that volume
- manual `.mpp` uploads through the existing UI/API

### Railway service setup

1. Create a new Railway service from this repo.
2. Attach a persistent volume and mount it at `/data`.
3. Set these environment variables:

```bash
PM_DASH_DATA_DIR=/data
PM_DASH_DB_PATH=/data/pm_dashboard.db
PM_DASH_EDITOR_USERNAME=your_editor_username
PM_DASH_EDITOR_PASSWORD=your_editor_password
PM_DASH_VIEWER_USERNAME=your_team_username
PM_DASH_VIEWER_PASSWORD=your_team_password
```

4. Deploy the service. The container starts with:

```bash
uvicorn pm_dashboard.main:app --host 0.0.0.0 --port $PORT
```

5. Set Railway health checks to `GET /healthz`.

### Runtime notes

- The app auto-creates the SQLite schema on first boot.
- The Java parser JAR is built into the image during Docker build.
- Uploaded `.mpp` files are stored under `/data/uploads`.
- Repo-root sample `.mpp` files are not required in production.

## Backups and Restore

Create an operator-run backup from the mounted data volume:

```bash
./scripts/backup_data.sh /data ./backups
```

Restore a backup into a clean volume mount:

```bash
./scripts/restore_data.sh ./backups/<timestamp> /data
```

Recommended restore workflow:

1. Stop the Railway service.
2. Restore the backup into the mounted volume.
3. Start the Railway service again.
4. Verify `GET /healthz` returns `status=ok`.
