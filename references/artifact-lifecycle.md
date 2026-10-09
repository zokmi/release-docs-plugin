# 產物生命週期

本規範適用生成與審查。暫存證據禁止納入版控；交付文件保持獨立可用。完整原始證據保留至最終審查與 hash 核對完成，成功後自動清除。使用者已要求本流程時，執行以下工具作為必要收尾，不再逐次詢問。

## 啟動與禁止版控

在目標 repo `.gitignore` 加入精準根目錄規則（保留其他規則）：

```gitignore
/.release-docs/
/docs/release-artifacts/
```

不得 ignore `docs/release-doc/`、正式 migration 或來源 SQL。ignore 不會取消已追蹤檔案；任何暫存或 legacy artifact 已 tracked/staged 時停止產製，回報路徑，禁止 `git add -f`、自動 `git rm --cached` 或覆寫既有產物。此為流程與工具的阻擋規則，不宣稱 `.gitignore` 能阻止使用者在流程外強制加入。

```text
python <插件>/skills/release-docs/scripts/artifact_lifecycle.py init --repo <repo>
```

`init` 先清除符合條件的到期 run，再回傳唯一 `run_id`、repo-relative `run_path`。所有本次 metadata、原始工具輸出、dacpac、測試資料、遮罩 log、commit-scope JSON、hash inventory 與完整審查輸入放在 `<repo>/<run_path>/`；不再新建 `docs/release-artifacts`、其他 docs 證據目錄或共用固定暫存。使用者提供原始 artifact 只讀，若需副本放入本次 run；清理不刪提供者原檔。獨立審查既有文件時也建立自己的 run。

每次寫入暫存與交付前執行 `check --repo <repo> --run <repo>/<run_path>`；交付前另執行既有 `validate_output_paths.py`。工具不會自動修改 ignore。若本輪只有 docs 日期待確認，可先分析但不產製暫存；先完成 ignore 與 init 才落地證據。

## 清除前的交付契約

01／01_索引調整（存在時）／02 必須包含完整執行 SQL，不依赖暫存檔；00／03／04／05 不得引用 `.release-docs/` 或 `release-artifacts/` 作為使用者需要開啟的路徑。索引調整檔保留 artifact 邏輯名稱、SHA-256、metadata 匹配條件、人工停止條件與和 01 的相依順序。03 保留 artifact 邏輯名稱、SHA-256、來源 revision／定位、轉換規則與排除單位；外部原檔的可保留位置可另記錄，不能冒充已永久保存。04 保存完成設定作業所需資訊，不能引用即將刪除的 inventory 補充必要內容。

必要審查仍需重讀完整證據，不能用摘要代替。審查結束在既有 `05_版更審查報告.md` 保存精簡、遮罩的永久摘要：完整 range／有序 commit scope、工作區納入決策、工具版本與遮罩命令、來源／執行單位對照及轉換解釋、證據相對名稱與 hash、成品 hash、SQL 內容狀態與部署驗證狀態。這是永久審查輸出，不是 raw log 封存；不得寫入 secrets 或原始設定值。

完成既有結構驗證、語意審查、最後來源 fingerprint 與 ignored evidence hash 比較後，將下列 JSON 填入 05 的唯一 HTML comment。由實際審查者填寫判定，工具不自行批准。所有 hash 必須對實際 bytes 計算。`documents` 包含存在的 00 至 04，不含 05；`evidence` 包含 run 內全部一般檔案（路徑相對 run），只排除根層 `run.json`、`.lock`。無資料庫實測時部署填「未執行」，不得假填通過。

```text
<!-- release-docs-lifecycle
{
  "run_id": "本次32位run-id",
  "sql_content_status": "通過",
  "deployment_status": "未執行",
  "scope": {"base": "解析後SHA", "target": "解析後SHA", "diff_mode": "two-dot", "working_tree_included": false},
  "tooling": [{"name": "專案工具", "version": "實際版本", "command": "遮罩命令", "exit_code": 0}],
  "unit_mapping": [{"id": "單位ID", "source": "revision:path:定位", "execution": "01_結構SQL.sql:定位", "transformation": "規則與差異說明"}],
  "documents": {"00_上線指引.md": "SHA256", "01_結構SQL.sql": "SHA256"},
  "evidence": {"artifact-metadata.json": "SHA256", "source.dacpac": "SHA256"}
}
-->
```

清單模式 scope 用完整有序 `commit_scope` 代替 base／target／diff_mode。schema 無差異時 `unit_mapping` 可為空陣列，tooling 仍記錄產製或來源核對方法。

```text
python <插件>/skills/release-docs/scripts/artifact_lifecycle.py finish --repo <repo> --run <repo>/<run_path> --documents <最終交付目錄>
```

只有 SQL 內容通過、部署通過或未執行、成品結構完整、receipt 與本次 run 相符、成品及完整 evidence hash 未變、沒有暫存引用時才清除本次 run。工具只檢查機械條件，不取代語意審查或最後來源 fingerprint 核對。成功後重查成品 hash 與 Git 狀態，在對話回報清理結果。刪除證據不使已審查成品自動變未通過，但之後的複審必須重新產製並核對證據；hash 摘要不等於證據仍可讀。不可只用歷史 fingerprint 自動續認通過。

## 失敗、中斷與到期

審查待確認／未通過、要求的部署驗證失敗、清除前核對失敗時執行 `fail --repo <repo> --run <repo>/<run_path>`，記錄 failed、UTC 到期時間為本次失敗後七天，解除執行鎖但保留證據。已確認本輪停止的中斷使用 `interrupt`，相同保留期。不得在其他產製／審查尚在進行時解除鎖。

每次啟動 `init` 自動 prune，也可明確呼叫 `prune --repo <repo>`：只清除已到期、無 `.lock`、狀態 failed／interrupted、有匹配 ownership manifest 的 run。程序崩潰未能標記的 running／locked run 保守保留；確認沒有執行者後才標記 interrupt。不新增背景排程，不宣稱七天到點立即刪除。清理失敗回報保留路徑與原因，不宣稱成功；禁止改用更寬的刪除指令。

刪除前核對實際 repo、固定 runtime 根、32位 run-id、ownership manifest 和整棵目錄；拒絕 symlink、junction／reparse point、hard-link 或非一般檔案。不刪交付文件、正式來源、其他 run、使用者輸入、既有 legacy 目錄。legacy 目錄須另外核對歸屬與所有文件引用、完成遷移後再處理。
