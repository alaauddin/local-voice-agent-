# Wazen Local Reliability and Performance Plan

> Implementation status: core reliability, Realtime session isolation, local staff-request
> persistence, history limits, activation modes, cookie-based kiosk access, and low-resource
> defaults are implemented and verified. The full target architecture is **not complete**:
> a dedicated `KioskStay` model, complete server-authoritative event stream and browser
> reconciliation, offline retry storage, broader browser/concurrency tests, and live deployment
> remain future work. The current deployment must set a strong `DJANGO_SECRET_KEY` before using
> signed kiosk cookies in production.

## Goal

Make the kiosk reliable on low-resource hardware while keeping Django as the local source of truth
for all application data returned to the frontend.

The browser should communicate with the local Django application for conversation state, messages,
tools, status updates, configuration, and history. OpenAI remains an upstream service controlled by
the backend.

For performance, the recommended design keeps Realtime audio on a direct WebRTC connection between
the browser and OpenAI. Relaying live audio through Django would increase CPU use, bandwidth,
latency, and operational complexity. The OpenAI API key and all authoritative application logic
must remain on the backend.

## Target Architecture

```text
Browser
  |-- Local REST and Channels
  |     |-- conversation state
  |     |-- normalized events
  |     |-- transcripts and history
  |     |-- validated tool calls
  |     `-- reset and session control
  |
  `-- WebRTC media only -------------------- OpenAI Realtime
                                                ^
                                                |
                                  Session configuration created
                                      by local Django backend
```

The frontend may receive provisional Realtime audio and transcript events for responsiveness, but
Django must validate, persist, normalize, and broadcast the authoritative event back to the UI.

## Phase 1: Reliability Fixes

### 1.1 Prevent permanently busy fallback requests

- Mark both `queued` and `streaming` user messages as `failed` when a Celery task fails.
- Publish exactly one terminal event for every request: `complete`, `failed`, or `cancelled`.
- Detect stale `queued` and `streaming` requests before accepting a new fallback request.
- Add a bounded request timeout and recovery path.
- Ensure reset cancels or safely invalidates work that is still running.

Acceptance criteria:

- An OpenAI exception cannot leave the kiosk permanently busy.
- A worker restart cannot block all later requests.
- A failed request has a terminal database status and a guest-safe frontend message.

### 1.2 Isolate stays and Realtime sessions

- Create a server-generated local session ID for each Realtime session.
- Bind that session ID to the current stay ID.
- Return both identifiers when Django creates the Realtime session.
- Require the local session ID on transcript and tool endpoints.
- Reject messages and tools belonging to an expired or previous stay.
- Invalidate every active session during stay reset.
- Add database uniqueness constraints for Realtime event IDs and tool call IDs.

Acceptance criteria:

- Events from an old browser session cannot enter a new stay.
- A tool call from an expired session cannot create a staff request.
- Duplicate delivery cannot create duplicate messages or actions.

### 1.3 Make reset deterministic

- Lock the active stay/configuration row.
- Invalidate active sessions first.
- Rotate the stay ID and delete the previous stay's private messages atomically.
- Commit the transaction before broadcasting the reset event.
- Close WebRTC and clear pending local state when the browser receives reset.
- Reconnect the socket and reload authoritative state from Django.

Acceptance criteria:

- Reset cannot partially complete.
- No previous-stay transcript appears after reset.
- All connected kiosk tabs converge on the new stay.

## Phase 2: Local Backend as the Frontend Authority

### 2.1 Add a local conversation bootstrap endpoint

Return only guest-safe data:

- current stay ID;
- signed local session ID;
- voice activation mode;
- enabled feature flags;
- current request status;
- recent paginated messages;
- wake phrase and inactivity settings.

### 2.2 Normalize events through Django Channels

- Define one versioned local event schema.
- Give every event a monotonically increasing sequence number.
- Persist important events before broadcasting them.
- Have the frontend render server-broadcast events as authoritative.
- Ignore duplicate and out-of-order events in the frontend.
- Keep tool execution entirely on the backend.
- Send only validated tool results back to OpenAI.

Suggested event envelope:

```json
{
  "version": 1,
  "event": "message.completed",
  "stay_id": "uuid",
  "session_id": "uuid",
  "request_id": "uuid",
  "sequence": 42,
  "payload": {}
}
```

### 2.3 Handle temporary local failures

- Retry failed transcript persistence with bounded exponential backoff.
- Optionally buffer unsaved events briefly in IndexedDB.
- Never treat the browser buffer as the permanent source of truth.
- Show a local synchronization state when persistence is delayed.

Acceptance criteria:

- Reloading the page restores the same conversation state.
- The UI does not depend on unverified client-only tool or message state.
- Temporary network interruption does not duplicate actions.

## Phase 3: Voice Lifecycle

### 3.1 Introduce explicit activation modes

Add:

```text
VOICE_ACTIVATION_MODE=wake|always_on|button
```

Recommended default for low-resource deployments: `wake`.

- `wake`: listen for the wake phrase, open one Realtime session, and close it after inactivity.
- `always_on`: automatically open and maintain Realtime while the page is active.
- `button`: access the microphone only after a guest action.

### 3.2 Correct session behavior

- Remove automatic Realtime startup when activation mode is `wake`.
- Restore the two-minute inactivity timeout in wake mode.
- Use one shared connection promise to prevent concurrent session creation.
- Apply exponential retry with jitter and a maximum retry count.
- Do not retry automatically after microphone permission denial.
- Reuse a microphone stream only for the lifetime of the active conversation.
- Cancel local and remote assistant output cleanly during barge-in.
- Close connections when the page is hidden unless always-on mode explicitly requires otherwise.

Acceptance criteria:

- Only one Realtime connection exists per browser tab.
- Wake mode does not keep a paid Realtime session open indefinitely.
- Interruption stops assistant audio without corrupting the next turn.

## Phase 4: Low-Resource Performance

### 4.1 Django and SQLite

- Keep one Daphne process for the single kiosk.
- Enable SQLite WAL mode and a suitable busy timeout.
- Run periodic WAL checkpoints.
- Avoid unnecessary database connection close/reopen cycles.
- Replace repeated application-level duplicate checks with database constraints.
- Add indexes for:
  - `(stay_id, request_id, role)`;
  - `(stay_id, status, role)`;
  - `(stay_id, created_at)`;
  - `(stay_id, tool_call_id)`;
  - session and event idempotency keys.
- Limit model history by both message count and total characters/tokens.
- Keep transactions small and avoid external HTTP calls inside transactions.

### 4.2 Celery and Redis

- Keep one Celery worker with the solo pool.
- Disable Celery result storage if results are never read.
- Set short visibility, task, and broker timeouts appropriate for a single kiosk.
- Keep Redis ephemeral and memory-capped.
- Limit Channels event payload size.
- Configure host `vm.overcommit_memory=1` to remove the Redis warning.
- Run `tini` as a proper subreaper for reliable child-process cleanup.

### 4.3 HTTP clients and integrations

- Reuse OpenAI and HTTP clients where lifecycle management is safe.
- Set connect, read, write, and pool timeouts explicitly.
- Limit retry counts and add jitter.
- Avoid blocking a guest response on slow SaaS forwarding.
- Never send the full property configuration when the integration needs only request fields.

### 4.4 Frontend

- Load only the newest 30 to 50 messages initially.
- Add cursor-based pagination for older history.
- Cap the number of rendered message nodes.
- Avoid sending base64 audio through Channels when possible.
- Prefer short-lived local audio URLs or browser speech fallback for backend TTS.
- Load only the active avatar video eagerly.
- Lazy-load other videos and settings UI assets.
- Pause videos, timers, and unused audio processing while the page is hidden.
- Deduplicate reconnect timers and event listeners.
- Cache fingerprinted static assets aggressively.

Acceptance criteria:

- Initial history responses remain small even during long stays.
- Browser memory does not grow continuously with conversation length.
- Idle mode consumes minimal CPU, network bandwidth, and OpenAI session time.

## Phase 5: Data Model and API Cleanup

### 5.1 Add explicit stay and session models

Introduce a `KioskStay` model:

- start and end timestamps;
- state: `active`, `closed`, or `reset`;
- privacy deletion timestamp;
- current sequence number.

Introduce a `RealtimeSession` model:

- session ID;
- stay relation;
- created and expiry timestamps;
- state: `active`, `closed`, `reset`, or `expired`;
- last activity timestamp;
- browser/session metadata that contains no sensitive fingerprinting data.

### 5.2 Add a real staff-request model

Do not use audit logs as the primary request record. Store:

- service and sanitized details;
- urgency;
- local reference;
- status;
- forwarding status;
- external reference;
- attempt count;
- last error;
- creation and update timestamps.

Audit logs should describe what happened, while staff-request records represent operational state.

### 5.3 Make SaaS forwarding asynchronous

- Save the local request first.
- Return local acceptance immediately.
- Forward it through a dedicated Celery task.
- Retry transient failures with bounded exponential backoff.
- Do not retry validation or authorization failures indefinitely.
- Surface forwarding state locally without promising success to the guest.
- Define clearly whether database or environment configuration takes precedence.

Acceptance criteria:

- A slow or unavailable SaaS cannot delay the concierge response.
- Every request remains visible locally even if forwarding fails.
- Operators can distinguish local acceptance from remote delivery.

## Phase 6: Security and Deployment

- Configure a strong `DJANGO_SECRET_KEY`.
- Configure `KIOSK_API_KEY` even when deployment is local-only.
- Replace permanent browser `localStorage` credentials with a short-lived signed kiosk session.
- Keep the service bound to `127.0.0.1` unless a trusted reverse proxy is configured.
- Add stricter throttling for Realtime session creation, reset, tool, and transcript endpoints.
- Add endpoint-specific request size limits.
- Validate OpenAI upstream content types and response sizes.
- Return guest-safe errors rather than raw internal exception text.
- Log request and session IDs without logging credentials or full guest transcripts.
- Continue preventing the OpenAI API key and SaaS tokens from reaching the browser.

Acceptance criteria:

- Default credentials cannot reach production.
- A browser cannot execute tools for another or expired stay.
- Logs remain useful without exposing private guest content.

## Phase 7: Verification and Observability

### Required automated tests

- OpenAI failure does not leave a streaming request.
- Worker restart does not permanently block the queue.
- Reset rejects late Realtime messages and tool calls.
- Two browser tabs receive consistent state.
- Duplicate transcript and tool events are idempotent.
- Repeated WebRTC connection failures respect retry limits.
- Barge-in cancels output safely.
- SaaS timeout does not delay local request acceptance.
- Long stays use paginated history.
- Redis loss produces a recoverable local error.
- Wake, always-on, and button activation modes behave independently.

### Development consistency

- Standardize local development and CI on Python 3.13, matching Docker.
- Make Django system checks and migration checks mandatory.
- Make all 22 existing tests pass in CI.
- Add coverage for the new failure and concurrency paths.
- Make Ruff pass; generated migrations may use an explicit lint exclusion.
- Add JavaScript linting and syntax checks.

### Local operational status

Provide a protected local status endpoint containing only:

- database and Redis health;
- worker heartbeat;
- current queue depth;
- number of active local sessions;
- last successful OpenAI connection time;
- last sanitized OpenAI error category;
- last SaaS forwarding result.

Do not include credentials, complete prompts, tool arguments, or guest messages.

## Implementation Order

1. Fix fallback failure status and stale-request recovery.
2. Add local Realtime session identity and stay validation.
3. Add database idempotency constraints.
4. Correct reset ordering and session invalidation.
5. Add explicit voice activation modes and connection locking.
6. Normalize authoritative application events through Django Channels.
7. Paginate history and cap frontend memory usage.
8. Introduce a staff-request model and asynchronous SaaS delivery.
9. Apply SQLite, Redis, Docker, and static-asset optimizations.
10. Harden secrets, kiosk authentication, and endpoint limits.
11. Complete concurrency, failure, and browser lifecycle tests.
12. Resolve lint issues and document the final operational workflow.

## Definition of Done

- The browser gets authoritative application state from the local Django service.
- Direct WebRTC is used only for low-latency Realtime media.
- No failed or interrupted request can permanently block the kiosk.
- Old sessions cannot write into a new stay.
- Reset reliably removes private stay memory.
- Staff requests remain locally durable when external SaaS is unavailable.
- Idle resource consumption is bounded and predictable.
- Long stays do not create unbounded API responses or DOM growth.
- Production uses explicit secrets and local kiosk authentication.
- All automated checks pass in the same Python version used in production.
