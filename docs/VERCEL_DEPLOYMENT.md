# Deploy the frontend and API together on Vercel

The repository is configured as one Vercel project. Vercel builds the Vite app,
serves it from the same domain as FastAPI, and sends API requests to the Python
function. The browser does not need a separate `VITE_API_URL` in production.

## One-time Vercel project settings

1. In the existing Vercel project, open **Settings → Build and Deployment**.
2. Set **Root Directory** to the repository root (`.`), not `frontend`.
3. Enable **Include files outside the root directory** if Vercel displays that
   option, then save and redeploy the latest commit.
4. Clear any old frontend-only **Build Command** or **Output Directory**
   overrides so Vercel uses the root FastAPI configuration.

The root `pyproject.toml`, `requirements.txt`, `main.py`, `build.py`, and
`vercel.json` tell Vercel how to install the backend and build the frontend.
The frontend and API share one origin, so the production browser uses relative
paths such as `/diagnose` and `/api/v1/auth/login`.

## Required Vercel environment variables

Add these in **Settings → Environment Variables** for Production (and Preview,
if preview deployments should use a separate database):

| Name | Value |
| --- | --- |
| `DATABASE_URL` | A persistent PostgreSQL connection URL using SQLAlchemy's asyncpg driver, for example `postgresql+asyncpg://USER:PASSWORD@HOST:5432/DATABASE?ssl=require` |
| `JWT_SECRET` | A unique, randomly generated secret; do not use the development default |

The database must support PostGIS because diagnosis geolocation and hotspot
queries use geography types and spatial functions. Supabase supports enabling
PostGIS from its database extensions settings; enable it before applying the
schema. Use the provider's connection-pooler URL if its direct connection limit
does not suit serverless functions.

Apply `backend/app/db/schema.sql` once to the hosted database. This creates the
PostGIS extension, enum types, and tables; the application intentionally does
not attempt production schema changes on every cold start.

The Vercel entrypoint defaults `ENVIRONMENT=production`, enables the built SPA,
and sets temporary uploads to `/tmp/cassavaguard-uploads`. Uploaded images are
available during inference but are not retained across function invocations.
The ONNX classifier is bundled from `ml/models/mobilenetv2_cassava.onnx`.
Vercel Functions cap each request body at 4.5 MB; the frontend reduces photos
larger than 4 MB before sending them so the app's 8 MB picker limit remains
usable on Vercel.

## Deploy

Commit and push the root deployment files to the branch connected to Vercel, or
run `vercel --prod` from the repository root. Check the deployment logs, then
open `/health` on the deployed domain. A healthy response includes
`"status":"ok"` and the selected classifier mode.

If login, diagnosis, history, or map requests fail, check that `DATABASE_URL`
is reachable from Vercel, the SQL schema has been applied, and `JWT_SECRET` is
set for that deployment environment.
