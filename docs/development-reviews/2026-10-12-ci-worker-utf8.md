# CI worker UTF-8 修正

## 根因與範圍

v0.1.36 Release run 38247627792 在 Windows Python 3.11 出現三個
`UnicodeEncodeError`。pytest 主程序的 `-X utf8` 不會傳遞至 xdist
新啟動的 interpreter，worker 在英文 Windows 使用 cp1252。

修正 CI 與 Release 測試步驟的 `PYTHONUTF8=1`，讓 worker 和子程序繼承
UTF-8 mode。不修改 SQL、審查契約、並行數、測試矩陣或發布閘門。

## 可重現證據

新增 `tests/test_ci_utf8.py`，讀取兩份 workflow 的測試環境設定，實際
啟動 UTF-8 主程序及未指定 `-X` 的子程序，驗證 worker mode 和中文字節。
修正前兩個案例都在 mode 0 與預期 mode 1 的比較上失敗。

修正後受影響範圍：252 passed、11 subtests passed，208.81 秒，無失敗或跳過。
範圍包含編碼回歸、release review、release gate、packaging。

完整六組遠端回歸以新版本 workflow 的實際結果為準；本文件不預先宣稱通過。
v0.1.36 標籤保留，不覆寫；下一版本為 v0.1.37。
