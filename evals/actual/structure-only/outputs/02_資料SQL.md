# 資料SQL — structure-only

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | structure-only → structure-only |
| base SHA | 531c6e8fdf96f6e6d25051d0f9389d60044902c7 |
| target SHA | e9ef25d82126c9fecf45ed3c42a82e2ae1f63bbc |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged/unstaged/untracked無額外部署來源；生成的精確五份成品排除，legacy簽核保留（如有） |
| 來源 | e9ef25d82126c9fecf45ed3c42a82e2ae1f63bbc:schema.sql:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | 無 |

## 異動、執行單位與檢查

無資料異動。完整 target:schema.sql:1 僅 CREATE，AGENTS.md:1 與全樹盤點沒有 migration、ORM、內嵌 SQL 或其他資料來源。

## 缺口與失敗處理

正式工具、artifact、維護窗口、備份與恢复流程未提供；停止部署直到補證，不能猜安全 DROP 或時間。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
