# GitHub Setup

当前交付物已经是一个带初始commit的本地Git仓库。建议先创建**私有**远程仓库：

- Repository name: `EV-Charging-Forecasting-Research`
- Owner: `Kato814`
- 不要勾选自动创建README、.gitignore或license（本地已存在）

## HTTPS推送

```bash
cd EV-Charging-Forecasting-Research
git remote add origin https://github.com/Kato814/EV-Charging-Forecasting-Research.git
git push -u origin main
```

## SSH推送

```bash
cd EV-Charging-Forecasting-Research
git remote add origin git@github.com:Kato814/EV-Charging-Forecasting-Research.git
git push -u origin main
```

## 推荐GitHub设置

- 默认分支：`main`；
- 开启 branch protection：PR合并、至少1次review、CI通过；
- 开启 Issues；
- 建立Project视图：`Inbox / To Read / Reading / Evidence Extracted / Reproduce / Decided`；
- Labels见 `docs/LABELS.md`；
- 仓库转公开前进行版权、数据许可、密钥和匿名信息审计。

## 当前连接限制

本次使用的GitHub连接仅支持读取/检索，未提供“创建仓库、提交文件或推送”的写权限。因此需要在GitHub网页端创建一次空仓库并执行上述推送。后续仓库内容仍可用本地Git、GitHub Desktop或Codex管理。
