# Task 1 implementation report

Status: complete. Implementation base: `16ef39b`. Scope: independent repository root manifests, README, MIT license, metadata-only Git collector, evidence and packaging tests. No external installation, publication, marketplace implementation or original Redmine repository changes.

## Implementation

- Added `plugin.json`, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`: `release-docs` / `0.1.0`, root-relative `./skills/`, no MCP or necessary external dependency. Root repository URL uses the existing private `zokmi/release-docs-plugin` repository provided by controller.
- Added `skills/release-docs/scripts/collect_release_evidence.py`: argument-list subprocess Git calls, NUL-separated names, repository-root discovery, explicit commit resolution, direct and unique merge-base comparison, independent staged/unstaged/untracked metadata, nonzero errors without JSON on failure. No file contents are read or emitted. Delete sources identify the pre-change revision; other committed sources identify target; working sources use index/working-tree markers.
- README documents actual comparison semantics, source boundaries, manager-only product installation policy and the still-pending later packaging work.
- Packaging tests verify manifests, identity, directory resolution, collector, license and README. Skills and templates intentionally remain later-task checks; no fake SKILL.md scaffolding was added.

## RED evidence

Command (PowerShell, repository root):

```powershell
& 'C:/Users/kenny/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -X utf8 -m unittest discover -s tests -v
```

Observed before production implementation:

```text
test_merge_base_diff_on_diverged_branches ... FAIL
test_no_changes ... FAIL
test_non_repository_fails ... FAIL
test_old_target_and_nul_paths_are_separate_from_working_tree ... FAIL
test_unknown_revision_fails_without_json ... FAIL
test_manifests_have_consistent_identity_and_resolvable_skills ... FAIL (3 subtests)
test_package_has_license_readme_and_collector ... FAIL
AssertionError: False is not true : Evidence collector is missing
AssertionError: False is not true : Missing manifest: plugin.json
AssertionError: False is not true : Missing manifest: .claude-plugin/plugin.json
AssertionError: False is not true : Missing manifest: .codex-plugin/plugin.json
AssertionError: False is not true : LICENSE
Ran 7 tests in 10.291s
FAILED (failures=9)
```

Exit code 1. Initial fixture runs hit sandbox system-temp permissions and missing-script diagnostics using Windows console encoding; those were test-harness errors, not valid RED evidence. Fixtures were moved to temporary directories within this checkout, subprocess Python uses UTF-8 mode, and the valid missing-tool failures above were then observed before implementation.

## GREEN evidence

Same full-suite command:

```text
test_merge_base_diff_on_diverged_branches ... ok
test_no_changes ... ok
test_non_repository_fails ... ok
test_old_target_and_nul_paths_are_separate_from_working_tree ... ok
test_unknown_revision_fails_without_json ... ok
test_manifests_have_consistent_identity_and_resolvable_skills ... ok
test_package_has_license_readme_and_collector ... ok
Ran 7 tests in 7.630s
OK
```

Exit code 0. During the first implementation run, Git matched a renamed fixture with another byte-identical deleted fixture; the single test failure was corrected by giving original fixture files distinct content, preserving the intended A/M/D/R scenario rather than changing the collector's rename logic.

Focused final checks:

```powershell
& 'C:/Users/kenny/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -X utf8 -m unittest discover -s tests -p 'test_evidence.py' -v
# Ran 5 tests in 14.926s; OK; exit 0
& 'C:/Users/kenny/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -X utf8 -m unittest discover -s tests -p 'test_packaging.py' -v
# Ran 2 tests in 0.005s; OK; exit 0
git diff --check
# no output; exit 0
```

## Limits and handoff

- Full skill behavior, template references and marketplace installation are deliberately pending Tasks 2–4. Current packaging validation does not claim an installable completed workflow.
- Collector is metadata-only; agent source reading, masking and semantic SQL review remain later skill work.
- Merge-base mode rejects multiple common ancestors rather than guessing one; `base_sha` is the effective comparison base.
- No database, network, plugin installation or external publish validation occurred.
- No subagents were spawned. Skills read: skill-creator, writing-skills, test-driven-development (including writing-good-tests), verification-before-completion.
