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
Copy-Item wai.yaml.example wai.yaml

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
- **Environment variables:** `WAI_ADMIN_KEY`, `WAI_ENCRYPTION_KEY`, `POSTGRES_PASSWORD`

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
.
├── pyproject.toml          # Python package metadata
├── docker-compose.yml      # Local PostgreSQL (+ optional Ollama)
├── wai.yaml.example        # Config template → copy to wai.yaml
├── run-local.ps1           # Local dev orchestration
├── scripts/
│   ├── db/                 # Database helpers (migrate, ensure DB, reset admin)
│   └── dev/                # Dev utilities (MCP test, Ollama GPU restart)
├── src/wai/                # Python backend
│   ├── api/                # Admin + health HTTP routes
│   ├── auth/               # Bootstrap and auth helpers
│   ├── config/             # YAML config loader
│   ├── crypto/             # AES encryption for secrets at rest
│   ├── db/                 # PostgreSQL connection + migrations
│   ├── middleware/         # Request ID and HTTP middleware
│   ├── proxy/              # OpenAI-compatible LLM proxy
│   ├── app.py              # FastAPI application factory
│   └── cli.py              # `wai` CLI entry point
└── ui/                     # React admin dashboard
    ├── public/             # Static assets
    └── src/                # Pages, hooks, components
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

Run migrations manually:

```powershell
python scripts/db/migrate.py
```
