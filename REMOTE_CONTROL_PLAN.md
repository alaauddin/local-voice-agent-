# LAN Remote Control Plan

## Goal

Let an administrator create a remote for a LAN controlled device, arrange its buttons, and assign one HTTP GET command URL to each button. Reusable templates provide button names and layout so a new remote only needs its device specific URLs.

Example command: `http://192.168.1.8/api/send?id=ESP01_01&code=85649F80`. The stored URL uses ordinary `&`; the backslash in the example's Markdown link is only link escaping.

## Data model

| Model | Main fields | Rules |
| --- | --- | --- |
| `RemoteTemplate` | `name`, `slug`, `category` (AC, fan, lights, other), `description`, `is_active` | Unique `slug`. A template describes buttons and contains no device URLs. |
| `RemoteTemplateButton` | `template` FK, `key`, `label`, `icon`, `sort_order`, `row`, `column`, `requires_confirmation` | Unique `(template, key)` and `(template, row, column)`. `key` is a stable name such as `power_on`. |
| `RemoteControl` | `name`, `slug`, `location`, `template` nullable FK, `is_active`, `sort_order`, `created_at`, `updated_at` | Unique `slug`. The template FK records where it came from; later template edits do not change existing remotes. |
| `RemoteButton` | `remote` FK, `key`, `label`, `icon`, `sort_order`, `row`, `column`, `command_url`, `is_active`, `requires_confirmation` | Unique `(remote, key)` and `(remote, row, column)`. A button has exactly one GET command. Empty `command_url` means unconfigured and cannot be pressed. |
| `RemoteCommandLog` | `remote` FK, `button` nullable FK, `stay_id` nullable, `source` (admin, kiosk, voice), `status`, `http_status` nullable, `duration_ms`, `created_at` | Records attempts and outcomes without storing full URLs or command codes. Keep errors short and scrubbed. |

Use `PROTECT` for template deletion while referenced by remotes, and for remote/button deletion while referenced by command logs, or use soft deletion via `is_active`. This preserves audit history. If the log is intentionally short lived, a retention job can delete old log rows first.

## Admin workflow

1. Register `RemoteTemplate` with a `RemoteTemplateButton` inline. The admin can set labels, icons, layout positions, order, and confirmation flags.
2. Add an **Add remote from template** admin view/action. The admin selects a template, names the remote and location, and submits once. A database transaction copies the template buttons into `RemoteButton` rows with blank command URLs. Copying is explicit and happens only at creation.
3. Register `RemoteControl` with a `RemoteButton` inline. Show each button's command URL, configured state, order, and active state. Highlight missing URLs and show a count such as `3/5 configured` in the remote list. Permit creating a remote without a template and adding buttons by hand.
4. Add a restricted **Test button** admin action on each configured button. Require a separate confirmation page showing the remote and button name because the command changes a physical device. Report success, HTTP failure, or timeout without displaying the full URL in logs.
5. Ship starter templates for common layouts: fan, AC, and lights. Seed only button labels and layout; administrators enter their actual URLs. Allow editing or adding templates in admin.

Template example: `Fan` with `Power On`, `Power Off`, `Speed +`, and `Speed -`. Loading it as `Pool fan` creates four buttons. An admin fills `Power On` with a URL such as the example above and fills the other three with their own codes.

## Command execution

- The browser or voice agent sends only a `RemoteButton` ID to Django. Django looks up the active button and reads its stored URL. Never accept a URL or command code from a guest request or an AI tool argument.
- Validate URLs when saved and immediately before sending: `http` only for the current LAN controller, allowed host/IP list in settings, expected path `/api/send`, no credentials or fragments, and bounded URL length. Start with an explicit allowlist containing `192.168.1.8`, configurable for later controllers. This prevents the feature becoming a general URL fetcher.
- Send one server side GET with a short connect/read timeout and no redirects. Do not automatically retry a command: a timeout may occur after the device has already acted. Mark non 2xx responses and network failures as failed.
- Check access before executing. Admin testing requires the appropriate Django model permission. Any kiosk endpoint uses the existing kiosk access mechanism and a CSRF protected POST. Add a per button cooldown and rate limit to avoid repeated presses. Keep sensitive devices such as pool stair lights manual only until voice use is explicitly enabled per remote.
- Record command outcome in `RemoteCommandLog` or the existing audit system. Log remote/button IDs and status, never the full URL, query string, or infrared code. Give the guest a brief success or failure response.
- Keep outbound HTTP outside database transactions. The command service is shared by admin testing, kiosk button presses, and any later voice tool, so all paths get the same validation and logging.

## Kiosk and voice integration

1. Add `GET /api/v1/kiosk/remotes/` returning active remotes and active buttons with labels, layout, confirmation flags, and `configured` status. Never return command URLs.
2. Add `POST /api/v1/kiosk/remote-buttons/<id>/press/` to execute a configured button through the shared command service. Disable unconfigured buttons in the UI.
3. Render a remote panel on the kiosk only when at least one active remote exists. Group buttons by remote and use the template layout positions.
4. If voice control is wanted, add a single strict tool such as `press_remote_button` whose argument is the button ID or stable remote/button keys. Build the available choices from active configured buttons and validate them server side at execution time. Do not expose raw URLs to the model. Require an explicit per remote `voice_enabled` flag and confirmation for sensitive actions.

## Build order and verification

1. Add models, constraints, migration, and admin template-copy workflow.
2. Add the shared command service with URL validation, timeout, audit, and admin test action.
3. Add kiosk list/press endpoints and remote panel. Add voice integration only after manual controls work.
4. Verify template copying, independent edits after copy, missing URL behavior, duplicate keys/positions, allowed versus blocked URLs, timeouts, no redirects/retries, permissions, rate limits, and log redaction. Mock the LAN controller in tests; perform one explicit physical-device test during deployment.

## Decisions to settle before implementation

- Which controller addresses and paths should be allowed? The example suggests `192.168.1.8` and `/api/send`.
- Should guests have manual kiosk control, voice control, or both? The data model supports both.
- Which commands require confirmation or must be unavailable to guests? Pool area lighting may need its own policy.
