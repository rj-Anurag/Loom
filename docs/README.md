# Loom Documentation Site

Standalone developer documentation for Loom, the project-scoped context layer for coding agents.

## Development

Requires Node.js 22.13 or newer.

```bash
npm ci
npm run dev
```

The local site runs at `http://localhost:3000`.

## Checks

```bash
npm run lint
npm run build
```

The site is built with Next.js, React, Tailwind CSS, and shadcn components. Content and UI live in `components/docs-site.tsx`; global tokens and documentation typography live in `app/globals.css`.

## Deployment

The production site is [loom-docs.vercel.app](https://loom-docs.vercel.app).
Vercel is connected to the `rj-Anurag/Loom` repository with `docs/` as the
project root. Pull requests receive preview deployments, and pushes to `main`
deploy to production automatically when the docs project is affected.
