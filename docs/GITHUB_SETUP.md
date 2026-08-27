# GitHub Setup

当前交付物是一个完整本地 Git 仓库，包含提交历史和版本标签。建议先发布为**私有仓库**，完成版权、数据许可和密钥审计后再决定是否公开。

## 推荐方式：GitHub Desktop

1. 解压 `EV-Charging-Forecasting-Research.zip`；
2. 在 GitHub Desktop 登录账号 `Kato814`；
3. 选择 **File → Add Local Repository**；
4. 选择解压后的根目录 `EV-Charging-Forecasting-Research`；
5. 点击 **Publish repository**；
6. Repository name 使用 `EV-Charging-Forecasting-Research`；
7. 勾选 **Keep this code private**；
8. 发布后确认 `main` 分支和版本标签均已上传。

不要把 ZIP 作为单个文件上传，也不建议通过网页端逐个拖入文件。网页上传会丢失本地 Git 提交历史和标签。

## 命令行方式

先在 GitHub 网页端创建一个空的私有仓库：

- Owner：`Kato814`；
- Repository name：`EV-Charging-Forecasting-Research`；
- 不要自动创建 README、`.gitignore` 或 License。

### HTTPS

```bash
cd EV-Charging-Forecasting-Research
git remote add origin https://github.com/Kato814/EV-Charging-Forecasting-Research.git
git remote -v
git push -u origin main
git push origin --tags
```

### SSH

```bash
cd EV-Charging-Forecasting-Research
git remote add origin git@github.com:Kato814/EV-Charging-Forecasting-Research.git
git remote -v
git push -u origin main
git push origin --tags
```

若已经存在名为 `origin` 的远程地址，改用：

```bash
git remote set-url origin <你的GitHub仓库地址>
```

## 发布后核验

```bash
git status
git log --oneline --decorate -5
git tag -n
git remote -v
```

当前交付版本应看到：

```text
v0.1.0-seed
v0.3.0-round2-review
v0.4.0-round2-extension
v0.5.0-problem-gap-review
```

## 推荐 GitHub 设置

- 默认分支：`main`；
- 开启 Issues；
- 建立 Project 视图：`Inbox / To Read / Reading / Evidence Extracted / Reproduce / Decided`；
- Labels 见 `docs/LABELS.md`；
- 有协作者后开启 branch protection：PR合并、至少1次review、CI通过；
- 仓库转公开前检查全文版权、数据许可、密钥、邮箱及匿名信息。

## 当前连接限制

本次使用的 GitHub 连接仅支持读取和检索，未提供创建远程仓库、提交文件或推送的写权限。因此需要由仓库所有者完成一次发布。发布后仍可继续通过本地 Git、GitHub Desktop 或其他开发工具管理。
