# Task 3 report: resumable production coordination

## Status

Implemented an adapter-driven `resume_release(repo, run_root, *, current_inputs, adapters=None)` entry point. It uses the Task 2 workflow state APIs to check owned run state, stage input fingerprints, output hashes, attempts, and stage completion. Failed adapter errors are recorded with a fixed sanitized summary; the original exception text is not persisted. Returned results remain `delivery_eligible=False` and do not claim SQL content passed.

`ProductionResult` now exposes a `resumable` flag. Existing `produce_release` callers retain the default `False` behavior.

## Changed files

- `skills/release-docs/scripts/produce_release.py`
- `skills/release-docs/scripts/resume_release.py`
- `tests/test_resumable_workflow.py`
- `.superpowers/sdd/2026-10-11-resumable-evidence-workflow/task-3-report.md`

`tests/test_release_review.py` was not changed; it has no receipt contract tied to this new adapter-driven API.

## Verification

- RED: `pytest.exe tests/test_resumable_workflow.py -q --basetemp .pytest-task3-red` — 6 failed because `resume_release` did not yet exist (`ModuleNotFoundError`), as expected.
- First GREEN attempt: `pytest.exe tests/test_resumable_workflow.py -q --basetemp .pytest-task3-green1` — 5 passed, 1 failed. The failing case exposed a stale in-memory state read after `resume_checkpoint` invalidated a tampered output.
- Focused fix verification: `pytest.exe tests/test_resumable_workflow.py::test_output_hash_change_restarts_at_corrupted_stage -q --basetemp .pytest-task3-hashfix` — 1 passed.
- Focused retry/safety verification after the final assertion change: `pytest.exe tests/test_resumable_workflow.py::test_retryable_failure_metadata_is_sanitized_and_never_passed -q --basetemp .pytest-task3-final-focus` — 1 passed in 10.31s.
- Required bounded suite command was started: `pytest.exe tests/test_resumable_workflow.py tests/test_release_review.py -q --basetemp .pytest-task3-final`. It was intentionally interrupted at the user's request before pytest produced a summary; no pass/fail total is available for that run.
- `git diff --check` — exit 0. Git emitted a line-ending warning for the pre-existing modified Task 2 report.

## Concerns

- Stage execution is adapter-driven. When `adapters` does not provide a callable for the first incomplete stage, resume stops with `stage_adapter_unavailable`; the existing monolithic `produce_release` pipeline has not been decomposed into built-in stage handlers.
- A fully completed run can be resumed without rerunning adapters, but the returned `ProductionResult` cannot reconstruct `inventory`, `artifact`, or `fingerprint` from Task 2 state alone and leaves those fields `None`.
- The combined required suite was interrupted, so the full Task 3 targeted verification remains incomplete.

## Commit

Commit requested: `feat: make release evidence production resumable`.
