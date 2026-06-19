# WAI UI

React admin dashboard for WAI — served by the Python backend in production, or via Vite during development.

## Layout

```
ui/
├── public/          Static assets (logo, favicon)
├── src/
│   ├── api/         API client
│   ├── components/  Layout shell + reusable UI
│   ├── hooks/       React Query data hooks
│   ├── lib/         Shared utilities
│   ├── pages/       Route pages
│   ├── styles/      Global CSS
│   └── test/        Vitest setup
├── index.html
└── vite.config.ts
```

## Development

```bash
npm ci
npm run dev
```

The dev server runs on `http://localhost:5173` and proxies API requests to the WAI backend (default `http://localhost:8090`). Start the backend with:

```powershell
..\run-local.ps1 -BackendOnly
```

Or:

```powershell
$env:WAI_DEV = "true"
python -m wai --config wai.yaml
```

## Production build

```bash
npm run build
```

The built assets in `dist/` are served automatically by the WAI server when present.
