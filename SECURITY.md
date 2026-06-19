# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in WAI, **please do not open a public issue.**

Instead, report it privately by emailing the maintainers with:

- A description of the vulnerability
- Steps to reproduce
- **Subject:** `[WAI Security] <brief description>`

We will acknowledge receipt within 48 hours and provide an estimated timeline for a fix.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Security Principles

WAI follows these security principles by design:

- API keys are hashed at rest (HMAC-SHA256)
- Upstream provider keys are encrypted (AES-256-GCM)
- Admin bootstrap credentials are shown once at first run
- RBAC enforced on all admin endpoints
- Secrets belong in `.env.local`, never in config files committed to git
