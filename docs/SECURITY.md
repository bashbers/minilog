# Security and privacy model

## Privacy promise

Minilog processes Baby, caregiver, health-adjacent, and free-text data only to provide the self-hosted application. It contains no advertising, profiling, telemetry, vendor account, remote analytics, remote crash reporting, third-party font or icon loading, CDN asset, or hosted identity integration.

All runtime requests remain on the Minilog origin chosen by the operator. The operator controls the server, DNS, proxy, VPN, filesystem, backups, and logs outside the containers.

## Trusted boundary

Minilog trusts:

- The Household's server administrator.
- The operating system and container runtime.
- Authenticated Owners and Caregivers within their documented permissions.
- A device while it is unlocked and an active Minilog session is available.

Minilog does not claim to protect data from a malicious server administrator, a compromised host, malware or a hostile browser extension on a caregiver device, or someone able to use an unlocked authenticated device.

## Threats addressed

| Threat | Principal controls |
| --- | --- |
| Internet interception | Operator-provided HTTPS or private VPN; Secure cookies |
| First-visitor takeover | Required one-time setup token; setup disabled after Owner creation |
| Credential theft | Argon2id password hashing, opaque sessions, token hashes at rest, login rate limits |
| Cross-site request forgery | SameSite session cookie and CSRF validation |
| Script injection | React escaping, plain-text notes, input validation, restrictive CSP, no active imported markup |
| Stolen browser token through JavaScript | HttpOnly session cookie; no bearer token in local storage |
| Silent concurrent overwrite | Required expected revision and explicit conflict response |
| Duplicate offline write | Client mutation UUID and persisted idempotency result |
| Parser abuse | Bounded file size, streaming/limited parsing, no execution, preview before commit |
| Image bombs and metadata leakage | Bounded dimensions and bytes, safe decode, metadata stripping, derivative-only storage |
| Sensitive logs | Allowlisted structured fields; payload and secret redaction |
| Supply-chain runtime calls | Bundled assets, pinned dependencies, CSP, automated no-third-party-request test |

## Data at rest

SQLite, profile-picture derivatives, retained PiyoLog sources, exports, upgrade snapshots, and manual backups are sensitive. Application-level database encryption is not included because an unattended container would need an accessible decryption key on the same host.

Operators should use encrypted host storage and encrypt copies leaving the server. Export and backup commands create restrictive-permission files and clearly report their location. The documentation must warn against placing exports in public or automatically synchronized directories without understanding that service's privacy policy.

The browser stores up to seven recent days for the selected Baby, the displayed profile picture, and pending creations in IndexedDB. Logout removes those values. Minilog cannot make an unlocked or compromised device safe by encrypting data with a key stored in that same session.

## Authentication details

- Setup, invitation, session, CSRF, and recovery tokens use cryptographically secure randomness.
- Only token hashes are persisted.
- Invitation tokens expire after 24 hours and are single-use.
- Sessions use a 30-day sliding expiry and can be revoked by device.
- Password changes revoke every other session.
- Authentication responses avoid revealing whether a username exists.
- Rate limits are conservative per source and username, with useful local security logs but no credential material.
- A server-side recovery command is deliberate, local, documented, and invalidates existing sessions.

Password policy should prioritize length and permit password managers and pasted passphrases. Minilog must not impose arbitrary composition rules or silently truncate passwords.

## Authorization

The backend enforces the matrix in [PRODUCT.md](./PRODUCT.md). The Owner-only boundary covers identity, Household settings, imports, exports, and permanent deletion. UI visibility is convenience, not security.

Every API query is scoped to the singleton Household and, where applicable, an explicit Baby. Record identifiers alone never bypass scope or permission checks.

## Input and output safety

- Notes and imported source text are stored and rendered as text, not HTML or Markdown.
- Files are accepted only at explicit image, PiyoLog-import, or Minilog-restore endpoints.
- File type is established by safe decoding and structural validation, not filename alone.
- ZIP restore rejects traversal paths, symlinks, excessive expansion, duplicate paths, invalid checksums, and unknown incompatible versions before mutation.
- CSV output uses spreadsheet-formula neutralization for cells beginning with formula-control characters.
- Numeric validation checks structure and broad technical bounds without making a medical judgment.

## Network and browser policy

Production sends a Content Security Policy that permits only bundled same-origin resources and the necessary inline-free application behaviours. It also uses appropriate MIME sniffing, framing, referrer, and permissions policies.

The default Compose publication is local HTTP and is not advertised as secure for untrusted networks. Documentation shows how to place Minilog behind an HTTPS reverse proxy or access it through a private VPN. The application must not trust forwarded headers unless its configured proxy boundary is explicit.

## Logging and diagnostics

Allowed logs include timestamps, severity, request ID, route template, method, response status, duration, lifecycle events, migration identifiers, sanitized exception class, and authentication security events.

Logs must not include request or response bodies, query values containing user data, Baby or Caregiver names, notes, medicine names, filenames supplied by users, image bytes, credentials, cookie values, tokens, or raw import lines. Readiness details exposed without authentication reveal no Household state.

There is no outbound crash reporter. A support bundle, if added later, must be an explicit Owner action with a preview and redaction.

## Deletion and residual data

Normal Care-record deletion uses a 30-day synchronization tombstone. Permanent identity, Baby, Household, picture, and retained-source deletion uses SQLite secure deletion and a truncating WAL checkpoint so removed values are not left in live database pages or sidecars. Existing operator-created exports, host snapshots, filesystem snapshots, flash-storage remapping, and backups are outside the application's ability to erase; deletion UI and documentation say so plainly.

Discarded profile-picture originals and replaced derivatives are not retained. An Owner may erase a former Caregiver's identity while keeping care history attributed to `Deleted caregiver`.

## Medical boundary

Minilog is an observational care log. It does not provide medical advice, prescribe doses, guarantee reminders, identify abnormal values, infer allergens, calculate developmental percentiles, or replace professional care. This boundary is expressed in product copy without using it as an excuse for inaccurate storage or unreliable software.
