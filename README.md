# EV-Charging-Forecasting-Research

面向**电动汽车充电功率/需求预测、概率预测、分布外泛化、冷启动、潜在需求识别、预测—优化耦合及可信联邦学习**的长期研究库。

> 当前版本：`v0.3.0-round2-review`
> 最近核验日期：2026-08-27
> 状态：完成两轮证据审查；主线进入最小门控实验设计，尚未冻结最终论文题目。

## 这个仓库解决什么问题

本仓库不是论文链接收藏夹，而是一套可审计的研究系统：

1. **文献证据库**：正式同行评议文献、前沿预印本和通用方法基础分开管理；
2. **最近邻占位审查**：记录已有方法已经解决什么、尚未解决什么，以及对选题的直接约束；
3. **数据与代码地图**：记录字段、许可、数据风险、适用任务及可复现仓库；
4. **研究方向门控**：以“科学问题—可识别性—数据可行性—最小证伪实验—停止条件”筛选方向；
5. **代码主仓骨架**：后续数据处理、预测、风险校准、调度和联邦学习代码统一进入同一工程；
6. **全过程追踪**：使用 Git commit、Issue、Pull Request 和 Decision Log 保存每次判断依据。

## 当前内容

- 正式同行评议/高可信条目：**46** 篇；
- 前沿观察条目（预印本/工作论文）：**14** 篇；
- 通用及相邻方法基础：**33** 篇；
- 第二轮最近邻证据记录：**18** 项；
- 候选数据集/仿真器：**10** 个，其中 **4** 个完成用途级字段审计；
- 相关开源仓库：**15** 个；
- 结构化重点阅读笔记：**17** 份；
- 第二轮候选方向：**8** 条；
- 已配置离线校验脚本和 GitHub Actions 工作流。

## 第二轮核心结论

第二轮将检索范围扩展到时间序列 OOD 泛化、选择性保形预测、冷启动与检索适配、供给删失与潜在需求、学习增强调度、因果策略响应及异构联邦预测。当前判断为：

1. **推进主线**：支持域感知的新站点/新城市选择性概率预测，并将原型检索和冷启动适配并入同一机制；
2. **只做可识别性门控**：潜在需求—服务功率—流失需求联合预测；
3. **作为第二阶段**：不可信预测下的学习增强鲁棒调度；
4. **暂缓**：策略条件因果预测与可信异构联邦；
5. **不作为独立主线**：基础模型替换、扩散模型替换、普通 OOD 模块、普通保形校准、普通聚类蒸馏式联邦。

详见：

- [`research/evidence_synthesis_v0.3.md`](research/evidence_synthesis_v0.3.md)
- [`research/decision_recommendation_v0.3.md`](research/decision_recommendation_v0.3.md)
- [`research/round2_direction_scorecard.csv`](research/round2_direction_scorecard.csv)
- [`research/novelty_red_lines.md`](research/novelty_red_lines.md)

## 重要边界

- 多数记录仍处于元数据、摘要或官方页面级核验；只有标记为 `full-text-*` 或 `reviewed-full` 的记录可视为完成全文证据提取。
- `literature/frontier_watchlist.csv` 中条目不能替代同行评议证据。
- “未检索到”不等于“文献空白”；任何创新主张仍需完成系统检索、全文核验和最近邻对比。
- 仓库不收录未经许可的付费 PDF。合法全文管理规则见 [`docs/COPYRIGHT_AND_ACCESS.md`](docs/COPYRIGHT_AND_ACCESS.md)。
- 数据集尚未全部下载并固定版本。字段可用性、缺失率、单位和许可必须以实际文件审计为准。
- 研究方向须通过最小门控实验后才能冻结。

## 推荐使用顺序

1. 阅读 [`docs/ROUND2_REVIEW_PROTOCOL.md`](docs/ROUND2_REVIEW_PROTOCOL.md)；
2. 查看 [`literature/round2_evidence_matrix.csv`](literature/round2_evidence_matrix.csv)；
3. 按 [`literature/reading_queue.md`](literature/reading_queue.md) 完成 P0 全文审读；
4. 审计 [`datasets/dataset_catalog.csv`](datasets/dataset_catalog.csv) 与 [`datasets/field_audit.csv`](datasets/field_audit.csv)；
5. 执行 [`research/evidence_synthesis_v0.3.md`](research/evidence_synthesis_v0.3.md) 中的 GATE-A 至 GATE-D；
6. 通过 [`research/decision_log.md`](research/decision_log.md) 冻结首个实验协议；
7. 在 `code/` 中实现无泄漏基线和最小门控实验。

## 快速校验

```bash
python scripts/validate_library.py
python scripts/build_reading_queue.py
python -m pytest code/tests
```

## 目录

```text
literature/    文献矩阵、最近邻证据、BibTeX、检索协议、阅读笔记
datasets/      数据集目录、字段审计、许可与下载记录
related_code/  相关开源仓库登记（不复制第三方代码）
research/      缺口图、方向评分、创新红线、假设与决策记录
code/          后续正式实验代码
scripts/       文献库校验、Crossref同步与队列生成
.github/       Issue模板、PR模板与CI
```

## GitHub 发布状态

当前交付是一个完整本地 Git 仓库，可通过 GitHub Desktop 或命令行发布到 `Kato814/EV-Charging-Forecasting-Research`。当前连接接口不具备远程仓库创建和推送权限，远端仓库仍需由仓库所有者发布。具体步骤见 [`docs/GITHUB_SETUP.md`](docs/GITHUB_SETUP.md)。

## 许可

仓库自有代码采用 MIT License；自有研究笔记采用 CC BY-NC 4.0。第三方论文、数据和代码遵循各自许可。
