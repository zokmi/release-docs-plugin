# 資料SQL — review-stale-report

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | review-stale-report → review-stale-report |
| base SHA | 28ffb8a6846bd39fd8956c7c907c5220e84514cf |
| target SHA | 3f5cdab3683de2a4e3518b422ed457aefe58b050 |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged/untracked無額外部署來源；unstaged docs/migration.sql新增INSERT Id=2，未納入指定target與執行步驟，納入決策待確認 |
| 來源 | 3f5cdab3683de2a4e3518b422ed457aefe58b050:docs/migration.sql:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | 無 |

## 異動、執行單位與檢查

無（完整docs/migration.sql僅CREATE與AGENTS.md盤點，没有其他資料來源）。

## 缺口與失敗處理

正式工具/方言、備份、artifact与恢复方案缺證；停止實際部署，不猜安全DROP。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。

本次文件更新：新增工作區來源納入決策欄；舊報告必須失效。

完整重新閱讀 working-tree:docs/migration.sql:1-2：CREATE加INSERT Id=2是候選混合單位，未批准納入所以不替代target版本。target:docs/migration.sql:1仍只有CREATE，指定版本資料異動無。若納入必須重看完整單位及部署取得方式，不重複執行CREATE。
