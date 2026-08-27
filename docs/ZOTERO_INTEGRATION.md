# Zotero Integration

推荐以 Zotero 管理PDF和引用，以Git管理证据与版本。

## 推荐设置

1. 安装 Zotero 与 Better BibTeX；
2. 建立集合 `EV-Charging-Forecasting`；
3. 将 Better BibTeX 自动导出到 `literature/references.bib`；
4. Citation key优先使用稳定格式：`authorYearShortTitle`；
5. Zotero附件保存在本地或机构允许的同步空间，不进入Git；
6. Git中的paper ID写入Zotero `Extra` 字段，例如 `Research-ID: P0034`。

## 去重

以 DOI 为主；无DOI时使用 arXiv ID；仍无标识符时使用“规范化题名+年份”。
