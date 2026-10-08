# CortexResearch — web

The frontend: Next.js 16 (App Router) + Tailwind v4. It is a pure UI — every
number on screen comes from the FastAPI engine in the parent directory.

```bash
npm install
npm run dev        # http://localhost:3001 (expects the API on :8000)
```

| Script | What it does |
|---|---|
| `npm run dev` | Dev server with HMR |
| `npm run build` | Production build |
| `npm run start` | Serve the production build |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | `eslint` |

## Layout

```
src/app/          routes: pulse (/), /research, /reports, /digests, /library, /topics
src/components/   shell, feed cards, report reader, live run pipeline
src/lib/          typed API client, hooks, formatters, shared types
```

## Conventions

`AGENTS.md` in this directory records the rules that are easy to regress —
the mobile shell has exactly one pinned bar, styling uses the theme tokens in
`globals.css` rather than raw hex, and the commands to run before committing.

Setup, architecture and the API contract live in the [root README](../README.md).
