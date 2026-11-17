# Vercel Services deployment

CassavaGuard is configured as two Vercel Services in one project:

- `frontend` builds the Vite app from `frontend/` and serves the SPA at `/`.
- `backend` runs FastAPI from `backend/` and serves the API, health check, and
  API documentation on explicit paths.

The model is a file dependency of the backend classifier, not an HTTP app. The
ONNX artifact is packaged inside `backend/models/`; `ml/` remains the source for
training and export tools. The frontend makes browser requests on the shared
domain, and Vercel rewrites those paths to the backend. There is no server-side
frontend-to-backend call, so no service binding is required.

## Vercel project settings

1. In Vercel, open **Settings → Build and Deployment** and set **Framework
   Preset** to **Services**. Services mode requires this selection as well as a
   `services` entry in the root `vercel.json`.
2. Set the repository **Root Directory** to `.` so Vercel can read the root
   `vercel.json` and both service directories.
3. Remove the prior Vite-only build/output overrides from the existing project.
   Each service uses its own framework detection and build settings.

## Backend environment

Add these project environment variables in Vercel for Production and Preview
as needed:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Persistent PostgreSQL URL using SQLAlchemy's asyncpg driver, e.g. `postgresql+asyncpg://USER:PASSWORD@HOST:5432/DATABASE?ssl=require` |
| `JWT_SECRET` | Unique random secret; never use the development default |

The database must support PostGIS. Enable that extension and apply
`backend/app/db/schema.sql` once before using diagnosis, history, or hotspot
features. The backend sets production mode and writes temporary uploads under
`/tmp/cassavaguard-uploads` on Vercel. Uploaded photos are not retained across
function invocations.

Do not set the frontend's `VITE_API_URL` to localhost in Vercel; leaving it
unset makes browser requests use the shared deployment domain. If you set a
custom backend model path, use `MODEL_PATH=models/mobilenetv2_cassava.onnx`.

## Public routes

The root `vercel.json` sends these paths to `backend`:

- `/api/*` for authentication, history, hotspot, farm, diagnosis and admin APIs
- `/diagnose` for image inference
- `/health` for the app's connectivity check
- `/docs`, `/docs/*`, `/redoc`, and `/openapi.json` for FastAPI documentation

All other paths go to `frontend`; its service-level rewrite serves `index.html`
for React Router deep links. The backend receives the original path, so its
existing `/api/v1/...` and `/diagnose` routes need no prefix changes.

Vercel limits function request bodies to 4.5 MB. The frontend resizes photos
larger than 4 MB before upload; the picker can still accept images up to 8 MB.

## Deploy and develop

Push the configuration to the Vercel-connected branch or deploy from the repo
root with the Vercel CLI. To run both services locally, use `vercel dev` (or
`vercel dev -L` without Vercel authentication).

After deployment, check `/health`. A healthy response reports `"status":"ok"`
and the classifier mode. See the Vercel Services documentation for service
routing, bindings, and service-specific configuration.
