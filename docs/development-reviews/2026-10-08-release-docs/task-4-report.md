# Task 4 integration report

Base: ab7e65f. Date: 2026-10-08. Workspace: independent `release-docs-project` on `codex/release-docs-plugin`. No subagents, no user-profile installation, no push/tag/publishing, no deployment SQL execution.

## Implementation

- Added Claude and Codex marketplace catalogs, both `release-docs-plugins`, plugin `release-docs`, local `./` root. Remote metadata/documentation uses real private `https://github.com/zokmi/release-docs-plugin`.
- README contains validated local CLI spellings for manager install/update/remove, prompts, private access boundary, annotated tag release procedure, no force tag overwrite, and no installed/published claims.
- Added CI Linux/Windows Python 3.11/3.12/3.13 matrix and release workflow for v* pushes/existing tag dispatch. Strict tag validation happens before checkout using env; manifests/resources/main membership/HEAD/tests before publish; read default/write release-job only; existing Release left unchanged; create --verify-tag --generate-notes. Actual Actions execution/publishing untested.
- Added read-only release checker and meaningful malformed-tag, mismatch/missing-resource and real Git side-branch/wrong-checkout tests, plus ordering/permission configuration guards.
- Fixed Task1 nonrepo fixture using GIT_CEILING_DIRECTORIES and asserted actual repository diagnostic. Fixed Task2 manual structural example to verify nvarchar max_length=200 and PK column Id. Packaging tests compare manifest versions dynamically so routine version bump does not require changing tests; release tests normalize synthetic fixture versions independent of product version.

## Actual semantic evaluation

Read entry/review skills, references and all five templates, then prepared 15 new independent Git repos with original revision/workspace sources. Did not copy task2 outputs. Task4 agent authored new source-grounded docs, separately re-read original Git base/target/workspace and all artifacts, judged semantics and wrote reports. One-shot transcription/read/report helpers remain in this SDD workspace and are not product generators or automated semantic graders.

`evals/results.md` and `evals/actual/<scenario>/` persist parameters/SHA, safe full source snapshots, original source-byte hashes, collector output, inspected-document hashes, round snapshots, judgments and outputs. Original Git fixtures retained under this SDD `actual-run/`. 14 scenarios have five final outputs, unknown-base stops/requests inputs with zero docs. Final document-review states: 1 通過 (no-changes), 1 未通過 (ORM deployment gap), 12 待確認 (missing mandatory environment/deployment evidence), 1 stopped/requested-input. No blanket PASS grading or deployment success claim.

- Six actual injected blockers: omitted Flags, duplicate mixed execution, wrong Notify:Enable key, known synthetic secret raw value, no expected verification, unsupported safe DROP. Round1 未通過 persisted; corrected all source-proven defects; re-read source/four docs in round2; remaining environment facts keep 待確認.
- Actually modified 02 and working-tree docs/migration.sql after an intentionally untrusted old PASS report. Old fingerprint/source identity changed, discarded conclusion, reread new source, kept specified target source separate, second review 待確認. New hash was never treated as proof of semantic correctness.
- Signed original raw bytes confirmed identical and new _v2 created; original hash record was corrected from pre-write LF string hashing to actual persisted CRLF original bytes. This was a record bug, not an original-file modification. Blank-signoff placeholder updated in-place with original placeholder evidence retained.
- Before writing each05: updated04 status, calculated final snapshot, compared base/target/diff_mode/committed/working_tree individually with already-reviewed snapshot. After writing05, exact snapshot unchanged. All final links resolve (including encoded # in original signed link), known fixture secrets absent in outputs.

Explicit unmet branches in results: docs-directory external symlink/junction agent write-stop branch; review-skill-unavailable fallback; approved-uncommitted inclusion branch; three-round exhaustion; independent blind/no-skill comparison. Named-document/report symlink rejects DID run successfully in unit suite. These unmet branches are not marked PASS. SQL/.NET execution, actual install/update/remove, remote Actions/Release and public listing are outside performed validation.

## Commands and observed outcomes

Python used throughout: `C:/Users/kenny/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe` with `-X utf8`.

1. `python -m unittest discover -s tests -p test_release.py -v` first failed: release checker missing. Packaging tests first failed: marketplace files missing. After implementation release4 and packaging3 passed. First temp fixture run hit restricted system-temp permissions; changed test temp dirs to workspace, passed real Git tests.
2. `python -X utf8 -m unittest discover -s tests -v`: 21 tests, 67.462s, OK, zero skips. Includes nonrepo diagnostic, old target/workspace, symlink guards, fingerprint invalidation, main tag and release guards.
3. After only synthetic version normalization in release test, affected `... -p test_release.py -v`: 4 tests, 2.574s, OK. No further production changes after whole suite.
4. `claude plugin validate .claude-plugin/plugin.json --json --strict`: success, zero errors/warnings. Same for `.claude-plugin/marketplace.json`. Root validation selects marketplace. `claude plugin validate skills` returns contents=[] and does not establish skill validation; individual directory returns no-manifest and SKILL.md returns JSON parse error. Both `quick_validate.py <skill>` attempts fail missing PyYAML; no package installed. stdlib packaging test checks actual frontmatter and all local links instead; this is limited structure validation, not a full YAML validator.
5. Read-only CLI help: Codex plugin add/remove, marketplace add/upgrade; Claude plugin validate/marketplace/update/uninstall. Codex normal-home help emits sandbox PATH/temp warnings; commands succeed. No install/update/remove command executed.
6. Isolated CODEX_HOME under this SDD: `codex plugin marketplace list --json` initially empty; `codex plugin marketplace add . --json` succeeds marketplaceName=release-docs-plugins, installedRoot=this independent project; list then shows matching root. Only temporary catalog configuration changed; no plugin add, actual user profile remains untouched.
7. `python -X utf8 evals/prepare_actual_fixtures.py`: 15 independent repos, no docs generated by preparer. The SDD document transcription/inspection/fix/finalization helpers then execute real Git/collector/fingerprint reads and source-grounded agent-authored outputs; finalization: 14 five-document outputs +1 stop, max2 rounds, source identity/05 stability/link/known-secret checks successful. These checks support recorded artifacts, not an automatic semantic PASS assertion.
8. `git diff --check`: clean (Git reports line-ending conversion warnings only). Scoped diff/manifest/reference reads checked. Parent Redmine checkout has pre-existing README/design-plan/spec/untracked independent checkout changes; this task wrote only this independent checkout/its ignored SDD, no personal skills or original Redmine code.

Sources for CLI/docs: official OpenAI `https://developers.openai.com/plugins/build/plugins` opened; GitHub CLI release create manual and Actions workflow syntax opened. Local CLI help has precedence for concrete installed Codex commands.

## Rulings and limits

- Used direct file-based agent skill execution allowed by task brief instead of installing to user profile or external agent API. Cost: same author/reviewer, weaker than blind independent evaluation; disclosed.
- Preserved all 15 actual outcomes and explicit unmet branches; did not silently promote manual examples or hash checks into semantic success. Missing deployment evidence correctly remains unresolved.
- No extra reviewer dispatched because task instruction expressly forbids subagents; parent performs overall review. No SDD deletion because evidence/report preservation is explicitly requested.

Ready for parent integration review. Commit identity appended below after commit.
Commits: ac976af integration; final raw-byte preservation commit recorded by git log. Post-commit artifact audit found56 CRLF-to-LF blob mismatches (all14x4 final docs); added evals/actual/** -text and renormalized archives. Same Git-blob audit GREEN:56/56 hashes match final snapshots. This preserves raw evidence across Linux/Windows clones. No production behavior changed.
Final commits: ac976af integration, dc62f33 preserved evidence raw bytes, final gitattributes whitespace annotation commit in git log. Preserved CRLF initially appeared as whitespace errors under default diff rules; scoped whitespace=cr-at-eol recognizes actual CRLF, diff-check passed without altering any evidence bytes.

## Task4 fix round1 — fixture reproduction destination isolation

Reviewer Important verified against a9d85a9: preparer had fixed RUN/ARCHIVE defaults and checked only RUN. On a fresh-clone simulation with absent default RUN and existing archive, it initialized an unwanted Git run before hitting an existing case-directory guard. That guard could leave original bytes unchanged while still violating preflight refusal; new case folders could mix archive generations. Existing CLI arguments were ignored rather than parsed.

Added required --run-root and --archive-root parameters. Both exact destinations are checked for existence/symlink before any directory creation, Git init, source/invocation/archive writes. Existing archive is rejected even when run does not exist; existing run is rejected before creating any archive. README and evals/results reproduction commands select fresh separate destinations and preserve committed evals/actual. Existing actual sources, outputs, snapshots and fingerprints deliberately untouched; reviewer Minor cross-scenario PK boilerplate remains deferred, no retrospective artifact edits.

Focused real-CLI tests use copied production preparer and a one-case Git input in fresh temporary clone-like destinations, not a rerun of the 15 agent evals. Existing archive contains invocation/source inventory/outcome/output sentinel files; full relative-path-to-raw-bytes mapping is compared before/after. Existing run marker bytes also checked.

RED command: python -X utf8 -m unittest discover -s tests -p test_evaluation_fixture.py -v
RED: 4 tests, 3.780s, failures=4. Missing arguments returned0 and wrote default outputs; existing archive preflight failed via unexpected .superpowers run creation; requested existing-run path was ignored; fresh requested run path was ignored. Full log task-4-fix-red.txt.
GREEN same command: 4 tests, 1.567s, OK. Full log task-4-fix-green.txt. Existing archive byte mapping identical, no new run/default .superpowers writes on refusal; existing run marker unchanged, no archive created. Fresh explicit destinations produce real Git and matching invocation. No full 15-scenario reevaluation or repeated broad suite; previous21-test suite remains recorded, scoped4 verify this change.

Verification: git diff --check passed. git diff --exit-code a9d85a9 -- evals/actual passed: all committed actual evidence unchanged. This fix changes only preparer, instructions and new focused tests. No installing, SQL, publishing, pushing, or subagents.
Fix-round1 commit: d4c7a89. Working tree clean after commit. Important finding addressed; deferred Minor unchanged.
