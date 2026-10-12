# Task 3 implementation report

Implemented review_fingerprint.py (Python standard library), real Git fixture tests, mandatory semantic review skill, report template, and three review integration scenarios.

## TDD evidence

Command (bundled Python): `python -m unittest discover -s tests -p test_review_fingerprint.py -v`

Initial harness run hit sandbox Temp write permissions; moved fixtures beneath the project. The next run exposed locale decoding of stderr; changed only test diagnostic decoding to replacement-safe UTF-8. Neither is counted as the intended RED.

RED before utility creation: 7 tests, 5 failures. Each successful-path test asserted returncode 0 and received 2, with `can't open file .../review_fingerprint.py: [Errno 2] No such file or directory`. The negative tests returned nonzero as expected; their meaning was verified again in GREEN.

```text
test_document_symlink_escape_fails ... ok
test_four_documents_change ... FAIL
test_missing_document_and_outside_docs_fail ... ok
test_scope_and_mode_change ... FAIL
test_stable_and_report_write_does_not_invalidate ... FAIL
test_staged_unstaged_untracked_and_docs_source_change ... FAIL
test_target_content_is_not_worktree_content ... FAIL
Ran 7 tests in 7.575s
FAILED (failures=5)
```

During GREEN implementation Git ls-tree did not support exclusion pathspecs; enumerate the actual commit tree and filter only the exact five output paths. Tree object IDs bind source bytes without exposing original text. Actual base/target SHA and diff mode are included; tracked staged/unstaged binary diffs and untracked content hashes are distinct working-tree evidence.

```text
test_document_symlink_escape_fails ... ok
test_four_documents_change ... ok
test_missing_document_and_outside_docs_fail ... ok
test_scope_and_mode_change ... ok
test_stable_and_report_write_does_not_invalidate ... ok
test_staged_unstaged_untracked_and_docs_source_change ... ok
test_target_content_is_not_worktree_content ... ok
Ran 7 tests in 26.694s
OK
```

Full-suite command: `python -m unittest discover -s tests -v`

```text
test_merge_base_diff_on_diverged_branches ... ok
test_no_changes ... ok
test_non_repository_fails ... ok
test_old_target_and_nul_paths_are_separate_from_working_tree ... ok
test_unknown_revision_fails_without_json ... ok
test_manifests_have_consistent_identity_and_resolvable_skills ... ok
test_package_has_license_readme_and_collector ... ok
test_document_symlink_escape_fails ... ok
test_four_documents_change ... ok
test_missing_document_and_outside_docs_fail ... ok
test_scope_and_mode_change ... ok
test_stable_and_report_write_does_not_invalidate ... ok
test_staged_unstaged_untracked_and_docs_source_change ... ok
test_target_content_is_not_worktree_content ... ok
Ran 14 tests in 39.042s
OK
```

Skill-creator quick_validate invocation was attempted but unavailable due to bundled runtime missing PyYAML (`ModuleNotFoundError: No module named 'yaml'`). Did not install dependencies or claim this check passed. Frontmatter contains name and description; linked report template resolves.

## Scope and review invariants

Exact four generated documents are hashed as raw bytes. Exact five generated document/report paths are excluded from source hashes; other docs sources remain included (real fixture covers docs/migration.sql). Report writing and staging four docs plus report preserve snapshot; changing any of the four docs invalidates it. Path must resolve within root/docs; outside required-file symlink fails. Snapshot contains no source or credential plaintext. CLI produces identity JSON only, never semantic approval.

Review requires actual revision sources and five substantive checks, blocking defects, insufficient evidence remaining pending, up to three review rounds, status update in 04 before final snapshot, and discard/review again if sources changed. Blank signoff with empty names/times and 未執行 remains a placeholder. Actual signoff requires preserved earlier version.

## Explicit integration transfer to Task 4

No semantic agent execution occurred in Task 3; authored scenarios and manual inspection are not execution evidence. Controller accepted transfer of actual source-read/use evaluation to Task 4. Must persist actual generated documents, review report and observed outcome for:

- `review-defects`: omitted SQL, mixed SQL executed twice, wrong config key, sensitive value, no expected validation, unsafe recovery; identify actual source evidence, block pass, correct and re-review.
- `review-stale-report`: real report creation then unchanged comparison, document mutation, source mutation including docs/migration.sql, and repeated semantic review.
- `blank-signoff-placeholder`: blank 未執行 remains editable draft; real signatures force new preserved version.
- Existing Task 2 scenarios remain Task 4's integration obligation, not satisfied by this task's manual checks.

Outstanding: agent-based skill baseline/GREEN and pressure evaluation required by writing-skills is not yet run; semantic correctness of generated deployment artifacts remains the integration gate. Utility tests prove identity behavior only.

## Review fix round 1 (base 1d424e7)

Rejected every symlinked named output, including 05 aliases targeting another source inside repo. Added a real Git fixture test before implementation; previously the CLI accepted the internal report symlink, allowing writing 05 to mutate source evidence and self-invalidate.

RED command: `python -m unittest discover -s tests -p test_review_fingerprint.py -k report_symlink -v`

```text
test_report_symlink_to_internal_source_fails ... FAIL
AssertionError: 0 == 0
Ran 1 test in 1.476s
FAILED (failures=1)
```

GREEN command (only requested test file): `python -m unittest discover -s tests -p test_review_fingerprint.py -v`

```text
test_document_symlink_escape_fails ... ok
test_four_documents_change ... ok
test_missing_document_and_outside_docs_fail ... ok
test_report_symlink_to_internal_source_fails ... ok
test_scope_and_mode_change ... ok
test_stable_and_report_write_does_not_invalidate ... ok
test_staged_unstaged_untracked_and_docs_source_change ... ok
test_target_content_is_not_worktree_content ... ok
Ran 8 tests in 32.214s
OK
```

Review skill now explicitly saves the reviewed snapshot, updates only the checked 04 status/report link, then compares final base/target/diff_mode/committed/working_tree against the reviewed snapshot before writing or accepting 05. Any source change discards the conclusion and requires fresh source reading and semantic review. Other document changes also require renewed review. This procedure change is documented, not claimed as executed agent evaluation; Task 4 integration obligation remains.

## Scoped resume-workflow re-review (base 41c46e6)

Added a producing-stage/input fingerprint to `production_result.json`; resume now rejects the durable result when that stage is invalidated or its current input fingerprint differs. Empty `output_files` iterables are materialized before the non-empty check. Durable results are written to a same-directory temporary file, flushed and fsynced, then atomically replaced; a failed replacement preserves the prior file and cleans the temporary file.

RED evidence: `pytest -q --basetemp .pytest-task3-rereview tests/test_resumable_workflow.py -k 'empty_output_file_generator or invalidated_stage_result or atomic_replace'` produced 3 failures. The failures showed the empty generator completing the source stage, the stale result being returned after source-input invalidation, and the result writer bypassing atomic replace. The atomic case was separately rerun after correcting its fixture and failed because replace was not called.

Focused regression command: `pytest -q --basetemp .pytest-task3-rereview-green2 tests/test_resumable_workflow.py -k 'empty_output_file_generator or invalidated_stage_result or atomic_replace'`

```text
3 passed, 12 deselected
```

Full resume suite command: `pytest -q --basetemp .pytest-task3-rereview-final tests/test_resumable_workflow.py`

```text
15 passed in 121.56s
```

The built-in `produce_release` integration and exact six-stage input mapping remain covered by the focused suite. No report outside Task 3 was changed for this review round.

## Final scoped review fixes (base 2824d79)

Addressed the three P2 findings in `resume_release.py`:

- Durable results now verify every declared output filename/hash, reject undeclared output-directory entries, and verify the assembled SQL evidence hash before persistence or return. A stale result invalidates the production checkpoint; deletion is regenerated through `produce_release`, while changed output or immutable assembly evidence is rejected under the existing producer safety checks.
- The built-in path is recognized at any incomplete source/fixture/local-validation checkpoint from the original `production_request`. The existing per-stage receipts let it finish the first three stages without unrelated adapters; production still runs through `produce_release` and its existing preflight and immutable evidence checks.
- `artifact.findings` and `artifact.unit_mapping` are recursively JSON-validated and passed through the existing `redact_text` utility before the atomic result write. Unsupported values, non-string mapping keys, and non-finite numbers fail closed.

Regression RED command selected the three initial cases from `tests/test_resumable_workflow.py`; result: **3 failed, 15 deselected**, with each failure showing the reported gap (partial checkpoint required an adapter, deleted generated output was accepted, and injected credentials remained in `production_result.json`).

Additional focused tamper command selected `generated_document_forces` and `artifact_evidence_is_rejected`; result: **3 passed, 17 deselected**. It covers modified and deleted generated documents plus modified immutable SQL evidence.

Final focused resume command: `python -X utf8 -m pytest -q tests/test_resumable_workflow.py`

```text
20 passed in 190.00s
```

The six-stage `current_inputs` contract and same-directory temporary write, `fsync`, and atomic replace behavior remain covered by this suite.

## Task 3 parameter-document fix

Addressed the requested parameter-document review findings in `render_release_documents.py` and the production sanitization handoff:

- Renderer metadata is preserved through sanitization and remains available to the business/module table and grouped sections; sensitive values continue through the shared redaction projection.
- Parameter sections are grouped by `(environment, service, parameter_group)`, so equal group names in different scopes cannot merge.
- Sparse array indexes are represented as keyed JSON with a pending/incomplete warning, without synthetic `null` entries or a suggestion that the partial JSON is directly applicable.

Focused command: `pytest.exe tests/test_release_documents.py tests/test_produce_release.py -q --basetemp=.tmp-task3-fix-final`

```text
84 passed, 3 skipped in 49.80s
```

The selected tests emitted a non-failing `pyreadline3` console shutdown warning (`OSError: [WinError -1073741816]`, `0xc0000008`). The requested `task-3-brief.md` was not present in this repository; the implementation scope was taken from the user's explicit fix list and the current diff/regression tests. No full suite was run.

## Final label collision fix

Parameter mapping and section labels now serialize the complete `(environment, service, parameter_group)` identity as compact JSON. This keeps labels injective when group names contain the former ` / ` scope separator. The regression case includes both ordinary scoped groups and a separator-containing group. A stale expectation for an incomplete descriptor was updated to retain its known environment and service in the composite label.

Requested focused command: `pytest.exe tests/test_release_documents.py -q --basetemp=.tmp-task3-label-final`

```text
63 passed, 3 skipped in 14.97s
```

The first run exposed the stale incomplete-descriptor assertion; after updating it, the requested command passed. Pytest emitted a non-failing `pyreadline3` shutdown warning (`OSError: [WinError -1073741816]`, `0xc0000008`). No other test command was run for this fix.
