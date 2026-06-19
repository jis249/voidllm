# Contributing to WAI

Thank you for your interest in contributing!

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .

# Configure secrets in .env.local (WAI_ADMIN_KEY, WAI_ENCRYPTION_KEY)
cp wai.yaml.example wai.yaml

# Backend + UI
.\run-local.ps1
```

Backend only:

```powershell
$env:WAI_DEV = "true"
python -m wai --config wai.yaml
```

## Project layout

```
src/wai/     Python backend (FastAPI)
ui/          React admin dashboard
wai.yaml     Server configuration
```

## Pull requests

- Keep changes focused
- Match existing code style
- Test locally before submitting
