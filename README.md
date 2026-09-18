# غروب — Sunset Resort Voice Concierge

A single-tenant Django concierge for one fixed chalet kiosk. Its primary voice path uses OpenAI
Realtime over WebRTC for native speech-to-speech conversation, semantic turn detection, and
natural interruption. Django creates the protected session, persists the stay transcript, and
executes strictly validated local tools. The Celery text/TTS pipeline remains available as a
fallback path.

## Docker quick start

```bash
cp .env.example .env
# Set OPENAI_API_KEY and replace DJANGO_SECRET_KEY in .env
touch db.sqlite3
docker compose up -d --build
docker compose ps
```

Open `http://127.0.0.1:8008/`. The stack contains Django/Daphne, the single Celery worker, and
Redis. Migrations and static-file collection run automatically before the web process starts.
The existing `db.sqlite3` is mounted into the application so chalet configuration and kiosk memory
survive image rebuilds. Redis data is kept in the `redis_data` Docker volume.

Useful commands:

```bash
docker compose logs -f web worker
docker compose restart
docker compose down
```

Do not use `docker compose down -v` unless you intentionally want to delete Redis data. The Celery
worker uses concurrency `1` for the single kiosk, and the application rejects a second fallback
chat request while a response is queued or streaming.

## Start automatically with the computer

All containers use `restart: unless-stopped`, so Docker restores them after a reboot. Install the
included systemd unit once to ensure the complete Compose project is also started and reconciled at
boot:

```bash
sudo ./deploy/install-autostart.sh
```

Check it with `systemctl status sunset-kiosk` and `docker compose ps`. To disable automatic startup,
run `sudo systemctl disable --now sunset-kiosk.service`.

Configure the singleton chalet row at `/admin/`. Its `chalet_number` is injected into the system
prompt and is never requested from the guest.

## API and socket contract

- `POST /api/v1/kiosk/chat/` with `{"message": "..."}` returns HTTP 202.
- `GET /api/v1/kiosk/messages/` returns the current stay's guest-visible memory.
- `POST /api/v1/kiosk/reset/` deletes current memory and rotates the stay identifier.
- `GET /api/v1/kiosk/health/` checks the database and Redis.
- `GET /api/v1/kiosk/status/` returns protected, guest-safe local operational status.
- `POST /api/v1/kiosk/realtime/session/` exchanges a browser SDP offer for a WebRTC answer.
- `POST /api/v1/kiosk/realtime/session/close/` invalidates the local Realtime session.
- `POST /api/v1/kiosk/realtime/messages/` persists a completed Realtime transcript item.
- `POST /api/v1/kiosk/realtime/tools/` validates and executes one allowlisted function call.
- `ws://127.0.0.1:8008/ws/kiosk/` accepts `{"type":"chat.message","message":"..."}`.

Socket output events are `connected`, `accepted`, `status`, `token`, `tool_status`, `complete`,
`error`, and `reset`. “Thought” streaming is represented by safe progress statuses; private
chain-of-thought is deliberately never exposed.

## Wake-word voice mode

The kiosk wake phrase defaults to **يا غروب**. `VOICE_ACTIVATION_MODE=wake` keeps the lightweight
wake listener active while the page is visible, then opens one WebRTC session for the conversation.
Use `always_on` only for installations that intentionally keep Realtime active, or `button` to
require an explicit microphone tap. Semantic VAD detects turn completion and the guest can interrupt
غروب while she is speaking. Wake-mode sessions close after two minutes of inactivity, a microphone
button tap, page hiding, or an explicit ending. Chrome/Edge on localhost or HTTPS is recommended.

Realtime defaults are configured with `REALTIME_MODEL=gpt-realtime-2.1`,
`REALTIME_VOICE=marin`, and `REALTIME_TRANSCRIPTION_MODEL=gpt-4o-transcribe`. The standard
OpenAI key never reaches the browser: Django sends the SDP offer and server-owned session config to
the unified `/v1/realtime/calls` endpoint.

Turn detection uses `semantic_vad` with high eagerness by default, preserving the meaning of short
Arabic pauses while keeping turns responsive. Set `REALTIME_VAD_EAGERNESS=medium` if guests tend to
speak slowly, or switch to `server_vad` and tune its threshold and silence values when required.

If `KIOSK_API_KEY` is set, pass it as `X-Kiosk-Key` to REST endpoints and as `?key=...` to the
WebSocket. Keep the service bound to localhost or a trusted chalet LAN. For public/TLS deployment,
set secure proxy/redirect, cookie, CSRF, and HSTS settings at the reverse proxy and Django layer.

## Verification

```bash
pytest
python manage.py check
```
