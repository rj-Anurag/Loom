# ADR-002: Public Self-Service Identity

## Status

Superseded by ADR-003 for public onboarding. The session, membership, and
agent-credential separation remains accepted.

## Context

The MVP required an operator bootstrap token to create every project. Public
users therefore could not onboard without receiving a project UUID and API key
from an administrator. Loom also needs to preserve agent-level provenance: a
human account should own projects, while each CLI, extension, and agent harness
must continue writing context under a distinct project-scoped identity.

## Decision

Add an administrative identity layer consisting of `users`, revocable opaque
`user_sessions`, and role-bearing `project_memberships`. Signup creates a user,
first project, owner membership, session, and first agent credential in one
database transaction.

User sessions may list and create membership projects and provision or revoke
client credentials. They cannot write context directly. All context, chat sync,
MCP, presence, and coordination operations continue to authenticate through an
`Agent` key. Raw session and agent tokens are returned only when issued; the
database stores SHA-256 token digests. Passwords use salted scrypt hashes.

The web dashboard uses a Secure, HttpOnly, SameSite cookie. CLI and extension
clients receive opaque bearer sessions, then mint separate `local` or `browser`
agent keys. Existing project keys and the explicit operator bootstrap flow
remain supported.

## Consequences

- Public onboarding no longer requires Render access or an administrator.
- CLI and extension credentials differ while accessing the same shared project.
- Existing projects remain usable but do not automatically acquire an owner.
- Account recovery and email verification remain deployment concerns for a
  later identity-provider/email phase; no fake email workflow is exposed.
- Redis is required for production signup/login rate limiting and already is a
  required production readiness dependency.

## Alternatives Considered

- Reusing one project key across every client was rejected because it destroys
  per-agent auditability and makes selective revocation impossible.
- Stateless JWT sessions were rejected because immediate logout and revocation
  are important for a context store containing private project history.
- Making the bootstrap endpoint public was rejected because it provides no
  account ownership, project discovery, or abuse controls.
