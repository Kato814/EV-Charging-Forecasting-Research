# EV-Charging-Forecasting-Research

面向**电动汽车充电功率/需求预测、概率预测、分布外泛化、充电灵活性、可信联邦学习及预测—优化耦合**的长期研究库。

> 当前版本：`v0.1.0-seed`  
> 首次核验日期：2026-08-27  
> 状态：研究基础设施已初始化；尚未冻结论文方向。

## 这个仓库解决什么问题

本仓库不是“若干论文链接的收藏夹”，而是一个可审计的研究系统：

1. **文献证据库**：正式同行评议文献、前沿预印本、通用方法基础分开管理；
2. **数据与代码地图**：记录可获取字段、许可、风险、适用预测任务及可复现仓库；
3. **研究缺口管理**：将“已有工作—未解决问题—可检验假设—实验门槛”串联；
4. **代码主仓骨架**：后续数据处理、预测、灵活性、优化调度、联邦学习和评价代码统一进入同一工程；
5. **全过程追踪**：使用 Git commit、Issue、Pull Request 和 Decision Log 保存每次判断依据。

## 当前内容

- 正式同行评议/高可信条目：**38** 篇；
- 前沿观察条目（预印本/工作论文）：**11** 篇；
- 通用方法基础：**13** 篇；
- 候选数据集/仿真器：**10** 个；
- 相关开源仓库：**8** 个；
- 已建立重点阅读笔记模板与首批预填笔记；
- 已配置离线校验脚本和 GitHub Actions 工作流。

## 重要边界

- 当前记录多数处于**元数据/摘要级核验**，不等同于全文系统评审；`review_depth` 字段对此明确标注。
- `literature/frontier_watchlist.csv` 中条目不能作为已同行评议结论使用。
- 仓库**不收录未经许可的付费 PDF**。合法全文管理规则见 [`docs/COPYRIGHT_AND_ACCESS.md`](docs/COPYRIGHT_AND_ACCESS.md)。
- 研究方向必须在完成核心文献全文审读、数据可用性核验和基线复现后再冻结。

## 推荐使用顺序

1. 阅读 [`literature/search_protocol.md`](literature/search_protocol.md)；
2. 按 [`literature/reading_queue.md`](literature/reading_queue.md) 完成 P0 文献；
3. 核验 [`datasets/dataset_catalog.csv`](datasets/dataset_catalog.csv) 中 P0 数据；
4. 更新 [`research/gap_map.md`](research/gap_map.md) 与 [`research/hypotheses.md`](research/hypotheses.md)；
5. 通过 [`research/decision_log.md`](research/decision_log.md) 冻结第一个可复现实验；
6. 在 `code/` 中建立数据基线和预测基线。

## 快速校验

```bash
python scripts/validate_library.py
python scripts/build_reading_queue.py
python -m pytest code/tests
```

## 目录

```text
literature/   文献矩阵、BibTeX、检索协议、阅读笔记
datasets/     数据集目录、下载与许可审计
related_code/ 相关开源仓库登记（不直接复制第三方代码）
research/     缺口图、候选方向、假设与决策记录
code/         后续正式实验代码
scripts/      文献库校验、Crossref同步与队列生成
.github/      Issue模板、PR模板与CI
```

## 许可

仓库自有代码采用 MIT License；自有研究笔记采用 CC BY-NC 4.0。第三方论文、数据和代码遵循各自许可。
