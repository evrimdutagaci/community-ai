# Community AI

An AI-powered platform that matches people to communities based on their interests, enabling real-time chat, AI-driven moderation, and digital member personas.

## Architecture

```
community-ai/
├── backend/          # FastAPI (Python 3.12) + PostgreSQL/pgvector
│   ├── app/
│   │   ├── routers/  # auth, communities, ws (WebSocket), dm, admin, metrics
│   │   └── services/ # agent, embeddings, clustering, moderation, …
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/         # React 18 + TypeScript + Vite + TailwindCSS
│   ├── src/
│   │   ├── pages/    # Login, Register, Onboarding, Community, Admin, Settings
│   │   ├── api/
│   │   └── store/
│   └── Dockerfile
├── docker-compose.yml       # Local development stack
└── docker-compose.prod.yml  # Production stack
```

## Features

- **AI Onboarding** — conversational onboarding via Claude to build an interest profile
- **Semantic Community Matching** — `pgvector` cosine similarity on BAAI/bge-small-en-v1.5 embeddings
- **Automatic Community Naming** — Claude generates community names and descriptions from member profiles
- **Real-time Chat** — WebSocket-backed channels per community
- **Direct Messages** — private 1:1 conversations
- **Digital Members** — AI personas that keep new communities active until real members arrive
- **Moderation & Guardrails** — prompt injection protection and output validation
- **Admin Panel** — ban users, override community status, view logs and metrics
- **Event Announcements** — Eventbrite integration refreshed daily
- **MCP Server** — community tools exposed via Model Context Protocol

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/)
- An [Anthropic API key](https://console.anthropic.com/)

## Quick Start

1. **Clone the repo**

   ```bash
   git clone https://github.com/evrimdutagaci/community-ai.git
   cd community-ai
   ```

2. **Configure environment**

   ```bash
   cp .env.example .env
   # Edit .env and set at minimum:
   #   ANTHROPIC_API_KEY=<your key>
   #   SECRET_KEY=<long random string>
   ```

3. **Start the development stack**

   ```bash
   docker compose up --build
   ```

   | Service  | URL                        |
   |----------|----------------------------|
   | Frontend | http://localhost:5173      |
   | Backend  | http://localhost:8001/docs |
   | Database | localhost:5433             |

4. **Register the first admin user** — use the `/admin/register` endpoint with the `ADMIN_SECRET` value from your `.env`.

## Environment Variables

Copy `.env.example` to `.env` and fill in the values. See `.env.example` for descriptions of each variable.

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `SECRET_KEY` | Yes | JWT signing secret |
| `DATABASE_URL` | Yes | SQLAlchemy async PostgreSQL URL |
| `POSTGRES_PASSWORD` | Prod only | Password for the `db` service (prod compose) |
| `ADMIN_SECRET` | Yes | Secret for the admin registration endpoint |
| `SIMILARITY_THRESHOLD` | No | Cosine similarity cutoff for community matching (default `0.65`) |
| `MIN_MESSAGES_FOR_PROFILE` | No | Minimum onboarding messages before profile generation (default `6`) |
| `RECLUSTER_EVERY_N_USERS` | No | Re-cluster communities after this many new users (default `10`) |
| `BRAVE_API_KEY` | No | Brave Search API key for web-search tools |
| `EVENTBRITE_API_KEY` | No | Eventbrite API key for event announcements |

## Production Deployment

```bash
cp .env.example .env
# Set ANTHROPIC_API_KEY, SECRET_KEY, POSTGRES_PASSWORD, ADMIN_SECRET
docker compose -f docker-compose.prod.yml up --build -d
```

The production compose builds optimized images and exposes only port 80/443 via the Nginx frontend.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 async, asyncpg |
| AI | Anthropic Claude (claude-sonnet-4-6), fastembed (BAAI/bge-small-en-v1.5) |
| Database | PostgreSQL 16 + pgvector |
| Frontend | React 18, TypeScript, Vite, TailwindCSS, Zustand |
| Runtime | Docker, Nginx |

## License

MIT
