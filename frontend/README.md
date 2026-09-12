# Loom frontend

The dashboard is a Next.js 16 App Router application. Material UI provides the
component system and its `sx` styling API, so the source tree intentionally has
no standalone HTML or CSS files.

From this directory:

```bash
npm ci
npm run dev
```

The development server listens on `http://127.0.0.1:3000` and proxies `/v1`,
`/health`, and `/ready` to `http://127.0.0.1:8000`. Override that backend with
`LOOM_API_INTERNAL_URL` when needed. Run the FastAPI service separately on port
8000 and set its `FRONTEND_URL` to the public frontend origin.

Production builds use `npm run build` and Next.js standalone output. The
production Compose topology can provision the frontend as a separate service.
The hosted frontend is deployed to Vercel and proxies API requests to
`https://loom-api-zzy0.onrender.com` unless `LOOM_API_INTERNAL_URL` overrides
that origin. The production frontend is available at
`https://loom-frontend-anurags-projects-cc627272.vercel.app`.
