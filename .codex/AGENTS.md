# Global Agent Instructions

These are my default working agreements across **every** project. A project's own
`AGENTS.md` (repo root or subdirectory) adds to or overrides this file where the two
conflict — always defer to the project-level file for anything specific to that codebase.

## How I Want You to Work

- Understand before you edit. Read the relevant files, before making changes.
- Make the smallest change that correctly solves the task. Don't refactor, rename, or
  reformat unrelated code "while you're in there."
- No speculative abstractions, config flags, or "might need this later" code. Build
  what was asked.
- Match the existing style, patterns, and idioms of the surrounding code rather than
  imposing your own preferences.
- If something is ambiguous, state the assumption you're making and proceed — unless
  the ambiguity is significant enough that guessing wrong wastes real effort, in which
  case ask one specific question.
- Never guess a generic build/test/run command. Figure out the project's actual commands
by checking, in order:

## Token & Context Efficiency

Being thorough doesn't mean being wasteful — match effort to what the task actually
needs. This applies across every section below.

- Don't repeat a check whose answer you already have. If you (or I) already know
  something works, verifying it again "just to be safe" burns tokens without adding
  information.
- Prefer targeted actions over exhaustive ones by default: read the files relevant to
  the task instead of surveying the whole repo, run the tests related to what changed
  instead of the full suite, search for what you need instead of re-reading large files
  in full. Go broader only when the change's reach genuinely calls for it (shared/core
  code, config, public APIs).
- Don't re-read a file you've already read this session unless it changed.
- Keep responses proportional to the task — a small fix doesn't need a long writeup,
  and a large change doesn't need a line-by-line narration.
- Don't paste back large chunks of code or command output that were already shown;
  reference or summarize instead.
- I test things myself too — you don't need to independently re-verify something at
  the end that I'm clearly about to check on my own. One solid verification pass is
  enough; skip the redundant second one "to be thorough."

## Testing

- Run the tests relevant to what you changed (see "Protect What Already Works" for
  when that means the full suite vs. a targeted subset).
- Add tests for new functionality, following the existing test file's structure and
  naming conventions.
- Never delete, skip, comment out, or loosen an assertion in a failing test just to make
  the suite pass. Fix the underlying bug, or explicitly flag the test as broken and why.
- If tests can't be run in this environment (missing services, no network, etc.), say so
  plainly rather than reporting an untested change as verified.

## Protect What Already Works

Breaking existing, working functionality while building something new is a common
failure mode — treat guarding against it as part of the task. Do this efficiently: one
solid check at the point that matters, not a duplicate pass at every step.

- Skip a separate "confirm the baseline still works" pass before starting just for its
  own sake — that's redundant with checking the end result after the change. Only do
  an explicit baseline check first if you have real reason to doubt the current state
  (resuming after a long gap, mid-refactor, unclear repo state, or I flag that
  something might already be broken).
- After building the new functionality, verify once: the new behavior plus whatever it
  could plausibly have affected. Scope this to the change's blast radius — run the
  test files/areas related to what you touched, and reach for the full suite only when
  the change touches shared/core code, config, or something with wide reach.
- When you do touch shared code (a shared function, component, schema, config, API
  contract, shared state), check the callers/usages that are plausibly affected rather
  than re-testing everything.
- If you can't verify existing functionality still works, say so explicitly rather
  than reporting the task as done.
- A change that adds the new feature but breaks something that used to work isn't
  finished — fix the regression, or if that's genuinely out of scope, flag it clearly
  as a known trade-off instead of leaving it unmentioned.

## Code Quality

- Run the project's linter/formatter before finishing and fix what it flags. Don't
  disable a rule or add an ignore comment to silence it unless the project already does
  this for the same rule elsewhere.
- Handle errors explicitly — no empty `catch` blocks or silently swallowed exceptions.
- No leftover debug prints, commented-out code, or dead code in the final diff.
- Prefer clear, explicit code over clever one-liners. Optimize for the next person
  reading it, not for brevity.

## Version Control

- Never commit directly to `main`/`master`/`trunk` unless explicitly told to.
- Write clear commit messages that explain *why*, not just *what*.
- Never commit secrets, credentials, API keys, `.env` files, or generated artifacts —
  check `.gitignore` is respected before staging.
- Don't force-push, rewrite shared history, or delete branches without confirmation.
- For anything large or destructive (bulk rename, schema migration, dependency major
  bump), summarize the plan before doing it.

## Dependencies

- Use the project's existing package manager and lockfile — don't mix package managers.
- Don't add a new dependency for something a few lines of standard-library code can do.
- Before adding a dependency, prefer one that's already used elsewhere in the project
  for the same purpose.

## Security

- Never hardcode credentials, tokens, connection strings, or secrets — use the
  project's existing config/env pattern.
- Treat all external input (user input, API responses, file contents) as untrusted;
  validate/sanitize it.
- Don't run destructive commands (`rm -rf`, force push, DB drop/migrate-down, `git reset --hard`)
  without confirming first.
- If you notice an existing security issue outside the scope of the current task, flag
  it — don't silently fix it (it may need review) and don't silently ignore it.

## Communicating Results

- When you finish, summarize what actually changed and why — not just "done."
- Call out anything you couldn't complete, skipped, or worked around, and why.
- Don't claim something builds, passes tests, or was verified unless you actually ran it.

## Definition of Done

- [ ] Code builds/runs
- [ ] Existing tests pass; new tests added for new behavior
- [ ] New functionality works *without* breaking previously-working behavior
- [ ] Linter/formatter passes
- [ ] No debug code, dead code, or unexplained TODOs left behind
- [ ] Change is scoped to what was asked — nothing extra bundled in