# Quickstart

## Prerequisites
- Docker + Docker Compose
- Telegram Bot token (from @BotFather)
- Your Telegram chat ID

## 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:
```
TELEGRAM_BOT_TOKEN=your-token-here
TELEGRAM_CHAT_ID=your-chat-id-here
TELEGRAM_ALLOWED_USERS=your_telegram_username

# Optional: real LLM (uses mock if empty)
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
```

## 2. Start everything

```bash
docker compose up --build
```

Services started:
- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- PostgreSQL: localhost:5432
- Redis: localhost:6379

## 3. Use via Telegram

Send to your bot:
```
/help           — show all commands
/alert prometheus pod-crash-001 high    — submit test alert
/status         — list active incidents
/pipeline       — view pipeline status
/pending        — approvals waiting
/approve <id>   — approve action
/deny <id>      — deny action
```

## 4. Use via API

```bash
# Submit alert
curl -X POST http://localhost:8000/alerts \
  -H "Content-Type: application/json" \
  -d '{"source":"prometheus","fingerprint":"test-001","severity":"high","domain":"infrastructure"}'

# Check pipeline status
curl http://localhost:8000/pipeline

# List pending approvals
curl http://localhost:8000/approvals/pending
```

## 5. Prometheus Alertmanager integration

Add to your `alertmanager.yml`:
```yaml
receivers:
  - name: agent-platform
    webhook_configs:
      - url: http://your-host:8000/webhook/alertmanager
        send_resolved: false
```

## Development (without Docker)

```bash
# Install dependencies
pip install -e .

# Run API
python run_api.py

# Run bot (separate terminal)
python run_bot.py
```
