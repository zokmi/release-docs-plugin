# SQL source and lifecycle analysis rules

- Read SQL at the evidence target revision, never implicitly from HEAD or the working tree. Deleted sources are evidence, not executable DROP instructions.
- Discover changed SQL, Database Project (`.sqlproj`), dacpac, migration and model snapshot candidates. A project or ORM migration needs an authoritative deployment SQL artifact; do not infer SQL from Up/Down methods.
- Each supported SQL artifact is one complete atomic unit, declared in its first line as `-- release-unit: {"unit_id":"core-table","phase":"SCHEMA","complete":true,"depends_on":[],"issues":["#5005"],"objects":["dbo.Core"]}`. The remainder is authoritative SQL, preserved unchanged in memory. Multiple declarations in one file require an explicit source split and review.
- Alternatively `evidence.execution_units` supplies the same descriptor with `source_path` and optional `covers` repository paths. This maps an authoritative SQL artifact to its migration or project sources. Missing, unannotated, invalid, partial, deleted or duplicate sources block production.
- Phase ordering is SCHEMA, REPAIR, DATA, VALIDATION, with dependency order within phases. Missing dependencies, cycles and dependencies on later phases block production.
- User exclusion intent such as `#5005` selects whole units by explicit codebase issue references. Shared ownership with another issue blocks exclusion; do not split SQL statements or infer ownership from a commit title. Unmatched intent blocks production.
- Preserve excluded existing database objects. List all transitive downstream dependencies; those dependencies block assembly until the scope is explicitly resolved. Do not quietly include dependent units or expand the user's exclusion authorization.
- Keep source path, resolved revision, raw source SHA-256, unit SQL SHA-256 and source location. Unit declarations are evidence requiring review, not automatic SQL safety certification. Baseline schema is hashed; complete index, FK and column definition checks belong to repair assembly and review.
- `lifecycle_exclusion_manifest.json` is the sole exclusion truth. Write it only inside `.release-docs/runs/<run-id>/`, with immutable source/unit metadata and review/authorization evidence. Do not persist source contents, SQL literals, arbitrary descriptor fields or freeform user intent. Never put lifecycle files in operator output.
- Record cleanup after successful delivery and seven-day retention for failed/interrupted runs. The lifecycle store records policy; the workflow owner performs cleanup and expiry handling after preserving permanent evidence required for reconstruction/review.

## SQL 最小語法與資料庫工具執行模式

- 正式交付優先使用 `database_tool_minimal` profile：`01_部署SQL.sql` 只保留按相依順序排列的基礎 T-SQL units 與可核對的註解 mapping。連線、權限、transaction、commit／rollback、timeout、錯誤攔截與執行模式由受控資料庫工具負責，不寫入 deployment source。
- minimal profile 的 source unit 禁止 session/configuration `SET`（例如 `NOCOUNT`、`ANSI_*`、`XACT_ABORT`、`IMPLICIT_TRANSACTIONS`）、`USE`、SQLCMD directive、`GO`、權限變更及自有 transaction。`SET IDENTITY_INSERT ... ON/OFF` 僅在確有 identity backfill 需求、成對出現且有來源證據時例外允許。
- framework profile 是相容舊流程的受控 fallback；其中 wrapper 的必要 metadata／transaction 控制不代表 source unit 可以自行加入 SET。新產製不得因方便而退回 framework；只有資料庫工具不支援 artifact-level transaction contract 時，才記錄例外原因與審查證據。
- 產製器必須保存 `sql_profile`、工具名稱／版本、命令、transaction policy、輸入／輸出 hash。review 需逐 unit 核對 source bytes 與最小語法 finding；任何非必要 SET 都在寫檔前阻擋，不以最高權限作為放寬理由。
- 執行流程改為：工具建立 fresh connection／transaction → 執行完整 `01` → 取得 per-unit 結果與 rollback/commit evidence → 關閉 session。文件不可要求操作人員另外執行 `sp_set_session_context` 或手動補 SET；若使用 framework fallback，必須明確標示其 compatibility reason。
- Metadata procedure（例如 extended property provider）不得以一般 `opaque_execution` 直接放行。若屬本次異動，需建立獨立 metadata descriptor：`operation_id`、`provider`／版本、object/action、遮罩後 arguments、source path/line、input hash、output SQL hash、reversible 與 transaction policy；provider 輸出的固定 SQL 才能納入 derived execution artifact。descriptor 或 mapping 不完整時維持 blocker，不能刪除 metadata 或把任意 `EXEC` 填成已審核。
- Review validator 必須依 lifecycle／artifact 的 `sql_profile` 與 unit `provider_kind` 分流：已核准 `metadata`／`dynamic_ddl` provider 的固定輸出可排除一般 `opaque_execution` 與 lexical `rerun_risk`，但仍須保留 provider descriptor、mapping、hash 與四輪 LocalDB evidence；未核准的 `EXEC`、缺 provider contract 或一般 unit 的未防護 mutation 仍阻擋。實際 rerun 通過只能作為同一 artifact 的補強證據，不得回溯放寬未核准 SQL。
