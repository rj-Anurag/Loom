# ADR-003: Google Identity With Terminal-Owned Project Creation

## Status

Accepted. Supersedes the public onboarding flow in ADR-002 while retaining its
session, membership, and agent-credential boundaries.

## Context

Email/password signup previously created a user, first project, and client key
from both the CLI and extension. That made account authentication, project
creation, and runtime authorization appear to be one credential loop. It also
made an extension-first user own a project that was not connected to a code
repository.

## Decision

Google OpenID Connect is the public identity boundary. The immutable Google
`sub` claim identifies a Loom user; email is profile data and remains unique.
The server stores Loom session-token hashes and Google profile claims, but does
not retain Google access or ID tokens.

CLI login uses Authorization Code with PKCE and a loopback redirect in the
system browser. The Chrome extension uses `chrome.identity` and exchanges its
short-lived Google access token for a Loom extension session. The account
dashboard uses Google Identity Services and exchanges an ID token for an
HttpOnly Loom session cookie.

Authentication creates only the user and session. The CLI is the primary
project-creation surface through `loom init`. The extension lists membership
projects and provisions a project-scoped `browser` agent only when a project is
selected for linking. Extension sessions are rejected by `POST /v1/projects`.

CLI agent keys are stored in a private user config file and are not printed or
written to a repository unless the user explicitly requests `--write-env`.
Every new machine and browser installation receives a separately revocable
agent credential.

## Consequences

- Signup and login become one `Continue with Google` operation.
- The same Google account sees the same project memberships in every client.
- An extension-first user sees a clear `loom login` / `loom init` instruction
  instead of creating an orphan project.
- Public deployments require separate Google OAuth clients for desktop, Chrome
  extension, and web dashboard clients.
- The unpacked extension uses a committed public manifest key, producing stable
  extension ID `cdahjeahjonafooajjbccipeaoefdjgm`; no private signing key is
  stored in the repository.
- Email/password endpoints remain available only when
  `EMAIL_PASSWORD_AUTH_ENABLED=true` for local development or migration.
