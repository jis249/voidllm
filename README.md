# WAI

Privacy-first LLM proxy and AI gateway — Python backend with OpenAI-compatible `/v1/*` API, admin dashboard, RBAC, MCP gateway, and usage tracking.

## Quick start

```powershell
# Start PostgreSQL (Docker)
docker compose up -d postgres

# Install Python dependencies
python -m venv .venv
.\.venv\Scripts\pip install -e .

# Configure secrets in .env.local (WAI_ADMIN_KEY, WAI_ENCRYPTION_KEY, POSTGRES_PASSWORD, provider keys)
# Edit wai.yaml for models and server settings

# Run backend + dev UI
.\run-local.ps1
```

Or backend only:

```powershell
$env:WAI_DEV = "true"
python -m wai --config wai.yaml
```

## Configuration

- **Config file:** `wai.yaml` (or set `WAI_CONFIG`)
- **Secrets:** `.env.local` beside the config file
- **Environment variables:** `WAI_ADMIN_KEY`, `WAI_ENCRYPTION_KEY`, `WAI_LICENSE`, `POSTGRES_PASSWORD`

## API

| Endpoint | Description |
|----------|-------------|
| `GET /v1/models` | List available models (Bearer API key) |
| `POST /v1/chat/completions` | OpenAI-compatible chat proxy |
| `POST /api/v1/auth/login` | Admin login |
| `GET /healthz` | Liveness probe |
| `GET /metrics` | Prometheus metrics |

## Project layout

```
src/wai/          Python backend
ui/               React admin dashboard
wai.yaml          Server configuration
run-local.ps1     Local dev orchestration
docker-compose.yml  Local PostgreSQL (+ optional Ollama)
```

## Database

WAI uses **PostgreSQL** locally.

| Setting | Value |
|---------|-------|
| Host | `localhost:5432` |
| Database | `wai` |
| User | `postgres` |
| Password | `POSTGRES_PASSWORD` in `.env.local` |

Start PostgreSQL:

```powershell
docker compose up -d postgres
.\run-local.ps1
```

The script creates the `wai` database automatically if it does not exist.
