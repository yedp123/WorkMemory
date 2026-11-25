---
trigger: model_decision
description: Load when writing tests, modifying existing features, or verifying read-only workspace safety.
---
# Testing & Change-Safety Rules

## Mandatory Read-Only Safety Proof
- Maintain `tests/safety/test_readonly_guarantee.py`.
- Before and after simulating workspace scans, live file observation, and indexing against a fixture folder, assert that:
  1. The exact set of files and subfolders is unchanged.
  2. Every file's SHA-256 hash and `mtime_ns` is identical.
  3. Zero sidecar or temp files were created inside the monitored folder.

## Anti-Regression Discipline
- Whenever fixing a bug or adding a feature, write at least one targeted test in `tests/unit/` or `tests/integration/`.
- Run `pytest` and `ruff check src tests` and confirm 100% pass before finishing.
- Never delete or weaken an existing test to make a new change pass.