# DiddiFiles Integration

**Status:** `proposed` for DiddiComms; DiddiFiles upload and signed-download
capabilities already exist.

## Ownership

DiddiFiles owns binary objects, upload sessions, metadata, purpose validation,
signed URLs, retention, and deletion. DiddiComms may eventually store only a
`file_id` plus message-safe metadata. Text-only messaging remains the MVP.

## Observed Provider Contract

DiddiFiles currently exposes:

| Method | Path | Scope |
|---|---|---|
| POST | `/v1/files/upload-session` | `files:write` |
| POST | `/v1/files/{file_id}/confirm` | `files:write` |
| GET | `/v1/files/{file_id}` | `files:read` |
| POST | `/v1/files/{file_id}/download-url` | `files:read` |
| DELETE | `/v1/files/{file_id}` | `files:write` |

The Support document that names
`/internal/v1/files/{file_id}/temporary-access` does not match the current
DiddiFiles route inventory. The teams must choose one canonical route before
marking the integration implemented.

## Target Identity And Privacy

Future S2S calls use audience `diddifiles`, an allowlisted DiddiComms or
DiddiSupport client, matching `X-Client-ID`, `X-Request-ID`, and least-privilege
read/write scopes. Static shared tokens are not part of the target contract.

Private message and Support attachments use short-lived signed URLs. Permanent
or public URLs are forbidden for private purposes. URLs, binary content,
tokens, EXIF data, and scan payloads must not enter conversation events or
ordinary logs.

## Required Future Flow

1. The authenticated user requests an upload session for an allowlisted
   DiddiComms or Support purpose.
2. The client uploads directly to storage using the temporary URL.
3. The client confirms the file.
4. DiddiComms stores only the validated `file_id` when media messages are
   enabled.
5. An authorized reader requests a fresh signed download URL.

Purpose, ownership, MIME type, size, scan/quarantine state, and conversation or
case association must be validated before access. The final purpose names,
malware-scanning states, and retention periods remain open questions.

## Retry And Errors

Upload-session creation and confirmation require stable idempotency behavior
before DiddiComms adoption. Reads and signed-download generation are safe to
retry. Missing file returns `404`; ownership or purpose denial returns `403`;
invalid type or size returns `422`; unavailable storage returns `503`.

## Conformance

Tests must cover ownership, wrong service client, missing scope, private versus
public purpose, expired URL, oversized file, invalid MIME type, quarantine,
delete/retention, and proof that URLs and binary data never enter DiddiComms
events or logs.
