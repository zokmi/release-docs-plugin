# release-docs

依目標 Git 專案的實際證據產出結構 SQL、資料 SQL、appsettings 異動、上線指引與必要審查報告。無必要 MCP、資料庫或外部服務相依；Redmine 可作為選用需求來源。文件審查不代表已執行 SQL、正式驗證或人工簽核。

插件名稱 `release-docs`，版本 `0.1.0`。產品安裝、更新、移除均透過 Claude Code／Codex 插件管理器；不以手動複製 skills 或獨立腳本作為安裝方式。遠端專案為 [zokmi/release-docs-plugin](https://github.com/zokmi/release-docs-plugin)。目前封裝骨架與蒐集器已建立；技能、範本及 marketplace 入口由後續實作提供，尚未驗證實際安裝。

## Git 證據蒐集契約

以下是插件內部工具介面，需 Python 3 與 Git CLI：

```text
python skills/release-docs/scripts/collect_release_evidence.py --repo "目標專案或巢狀目錄" --base 基準REV --target 目標REV --diff-mode direct
```

`direct` 比較解析後基準 commit 與目標 commit 的樹；`merge-base` 比較兩者唯一共同祖先與目標 commit 的樹，JSON 的 `base_sha` 記錄實際使用的共同祖先。不明 revision、非 Git 目錄、無共同祖先或多重共同祖先均失敗，不猜測 main 或輸出位置。

stdout 為 JSON，包含 `schema_version`、Git 根目錄、實際 base／target SHA、diff 模式、已提交異動及獨立工作區清單。使用 NUL 分隔路徑，保留中文與空白。檔案项記錄 Git status、rename 原路徑、目前路徑與 `source_revision`；刪除檔取比較前來源，其他已提交檔取目標來源。工作區來源以 `index`／`working-tree` 標示，staged 相對目前 HEAD、unstaged 相對 index、untracked 為未追蹤檔，均不表示已納入部署。

工具只輸出路徑與 revision 等中繼資料，不輸出 SQL、設定原文或差異內容。閱讀指定來源需使用解析後 revision 的 Git 內容；不可把工作區內容冒充舊 target。明確 commit 清單需由技能逐一讀各 commit parent 差異與完整來源，本工具不把該清單偽裝為連續範圍。

## 開發驗證

```text
python -m unittest discover -s tests -v
```

測試使用臨時 Git repo；Windows 受限環境的 fixture 建於專案根目錄並清理，不需外部服務。
