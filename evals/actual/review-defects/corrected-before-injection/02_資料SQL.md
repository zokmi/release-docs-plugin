# 資料SQL — review-defects

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | review-defects → review-defects |
| base SHA | e5561caa5de808a829a75e6df6dd39c26682c85f |
| target SHA | d4245edc157f888e1cc13bd9c8a357e6200cc405 |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged/unstaged/untracked無額外部署來源；生成的精確五份成品排除，legacy簽核保留（如有） |
| 來源 | d4245edc157f888e1cc13bd9c8a357e6200cc405:appsettings.json:完整閱讀; d4245edc157f888e1cc13bd9c8a357e6200cc405:schema.sql:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | 無 |

## 異動、執行單位與檢查

SQL-001同schema.sql:1 INSERT dbo.Flags VALUES(1)，一列Id=1，無PK/存在性保護，不直接重跑。新表且无並行寫入時SELECT Id FROM dbo.Flags; 預期唯一一列1，COUNT=1；查詢待方言確認，未執行。

## 缺口與失敗處理

正式工具/方言、備份、設定消費程式及正式artifact缺證。禁止宣稱DROP TABLE可保證安全；失敗停止、保留已提交證據，回復需備份與相容性方案。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
