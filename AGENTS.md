# Instructions for agents working on web-app-launcher

These instructions apply to the entire repository. Follow more specific
`AGENTS.md` files when present.

## Scope and compatibility

- Inspect the existing diff before editing. Preserve the user's unfinished changes;
  do not overwrite, revert, or format unrelated work.
- Keep changes focused on the requested task. Prefer straightforward solutions
  over new frameworks, speculative abstractions, or unrelated refactoring.
- This application is still being developed for its first release. Target the
  latest stable Fedora Linux and its current Python, Qt, libraries, and tools.
  Do not add support for obsolete Linux distributions or runtimes.
- Do not preserve backward compatibility for unreleased interfaces unnecessarily.
  Update APIs, callers, models, and tests together instead of adding deprecated
  aliases, permissive parameter types, legacy format readers, or compatibility
  fallbacks. Add compatibility only when the user explicitly requests it.
- Use current platform APIs directly. If a change requires newer dependencies or
  Python, keep the declared requirements and checks consistent with that change;
  avoid unrelated dependency upgrades.
- Do not stage, commit, or push unless explicitly instructed. Leave changes ready
  for review.
- Keep this document limited to durable project guidance, not change history.
  Keep README content focused on instructions for application users.

## Code style and design

- Follow the existing Python and QML conventions and `.pre-commit-config.yaml`.
  Let pre-commit handle formatting, linting, and type checking. Fix the code
  rather than weakening checks.
- Write identifiers and code comments in English. Explain non-obvious contracts,
  ownership, and decisions rather than restating the code.
- Separate logical sections within functions with a blank line, such as setup,
  validation, processing, and result handling. Keep closely related statements
  together.
- Avoid magic numbers. Prefer standard library classifications and named platform
  constants; otherwise define descriptive constants for limits, timing, binary
  layouts, and presentation values throughout the project. Keep literal test data
  and self-explanatory indexes, counters, and arithmetic readable.
- Use precise types for internal interfaces. Use enums for closed command sets
  and the existing Pydantic models for structured messages and validation.
  Avoid accepting arbitrary strings or coercing invalid external field types
  merely to accommodate old callers.
- Define shared validation rules once and reuse them at input boundaries.
  Keep validation separate from actions with side effects.
- Prefer module-level helpers or methods to nested helper functions. Use closures
  where callbacks or fixtures need captured state.
- Keep QML focused on presentation and application behavior in Python.
- Use existing Qt mechanisms for runtime paths, locking, socket IO, timeouts,
  and object lifetimes. Clean up owned resources on failure and shutdown, and
  keep asynchronous socket handling nonblocking.
- Pass browser executables and arguments separately. Preserve argument boundaries
  and explicit error reporting and process cleanup.

## Container development and verification

- Run application execution, dependency installation, tests, and pre-commit tools
  inside the project's Podman container through `just container-*` recipes.
  Host file editing and Git inspection are allowed; do not modify the host Python
  environment or invoke the underlying development tools directly on the host.
- Use `justfile` and `tests/Containerfile`. If the image is missing, run
  `just container-build-image`. If Podman is unavailable, report the blocker and
  skipped checks instead of substituting host execution.
- For code changes, run `just container-test-all` before declaring the work
  complete. It runs pre-commit followed by the full headless test suite.
  Use `just container-test-unit` or `just container-test-integration` for focused
  checks while working.
- Pre-commit may modify files. Review its changes, rerun until it passes without
  further edits, and test the final code.
- For documentation-only changes, run `just container-pre-commit <paths>`;
  application tests are unnecessary. The pre-commit recipe also supports
  untracked files, so do not stage files just to check them.
- Consult `justfile`, `tests/Containerfile`, and `pyproject.toml` for commands and
  dependencies rather than duplicating their inventories here.

## Tests and reporting

- Keep tests proportional to the behavioral change and its risk. Reuse existing
  fixtures and add regressions for observable behavior, not implementation details
  or dependency version numbers. Documentation and formatting need no new tests.
- Use isolated temporary paths and environments. Never touch real user
  configuration or profiles, launch a real browser, or rely on live network
  services in automated tests. Stub external effects; use real local sockets
  when checking IPC transport behavior.
- Account for Qt object lifetimes and finish asynchronous cleanup before fixture
  teardown. Do not weaken tests or fix unrelated failures to make a check pass.
- In the final response, briefly state what changed, which checks passed, and
  any failures or verification limits. Do not claim skipped checks passed.
