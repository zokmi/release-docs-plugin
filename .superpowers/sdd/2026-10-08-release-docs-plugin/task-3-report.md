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
