# WAI UI

The admin dashboard for WAI — a React single-page application served by the Python backend (or via Vite in development).

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
