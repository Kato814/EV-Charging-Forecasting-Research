# EV-Charging-Forecasting-Research

面向**电动汽车充电功率/需求预测、概率预测、分布外泛化、冷启动、潜在需求识别、预测—优化耦合及可信联邦学习**的长期研究库。

> 当前版本：`v0.4.0-round2-extension`
> 最近核验日期：2026-08-27
> 状态：完成第二轮及两组扩展证据审查；启动结构 OOD、运营车队和 performative 三条门控，尚未冻结最终论文题目。

## 这个仓库解决什么问题

本仓库不是论文链接收藏夹，而是一套可审计的研究系统：

1. **文献证据库**：正式同行评议文献、前沿预印本和通用方法基础分开管理；
2. **最近邻占位审查**：记录已有方法已经解决什么、尚未解决什么，以及对选题的直接约束；
3. **数据与代码地图**：记录字段、许可、数据风险、适用任务及可复现仓库；
4. **研究方向门控**：以“科学问题—可识别性—数据可行性—最小证伪实验—停止条件”筛选方向；
5. **代码主仓骨架**：后续数据处理、预测、风险校准、调度和联邦学习代码统一进入同一工程；
6. **全过程追踪**：使用 Git commit、Issue、Pull Request 和 Decision Log 保存每次判断依据。

## 当前内容

- 正式同行评议/高可信条目：**61** 篇；
- 前沿观察条目（预印本/工作论文）：**18** 篇；
- 通用及相邻方法基础：**44** 篇；
- 第二轮直接证据：**32** 项；反馈、结构变化与运营车队扩展证据：**21** 项；
- 第二轮检索簇：**11** 组；扩展检索簇：**8** 组；
- 候选数据集/仿真器：**14** 个；用途级字段审计 **10** 条，详细 Markdown 审计 **8** 份；
- 相关开源仓库：**22** 个；
- 结构化重点阅读笔记：**33** 份；
- 第二轮宽域候选方向：**13** 条；进一步扩展评分方向：**8** 条；
- 已配置离线校验脚本和 GitHub Actions 工作流。

## 第二轮扩展核心结论

本轮审查了严格 OOD 与校准、极端峰值、服务删失、数据可靠性、仿真—真实迁移、决策诱导分布变化、网络扩建反馈、逆向偏好学习以及运营车队场站。当前判断为：

1. **主门控**：网络扩建下的支持域感知结构 OOD 概率预测。必须联合描述新旧站需求再分配，并允许拒绝/回退；
2. **平行门控**：运营车队的路线—返回—能耗联合概率预测与鲁棒场站调度；
3. **高风险门控**：决策诱导分布变化下的 performative 闭环预测。先验证行动—需求响应是否可识别；
4. **数据硬门控**：排队、故障、放弃和站间替代下的服务可实现负荷；
5. **横向评价模块**：峰值/尾部风险、整轨迹覆盖、选择性预警和安全回退；
6. **继续暂缓**：逆向灵活性、完整决策聚焦场景学习及可信联邦集成。

详见：

- [`research/evidence_synthesis_v0.4.md`](research/evidence_synthesis_v0.4.md)
- [`research/decision_recommendation_v0.4.md`](research/decision_recommendation_v0.4.md)
- [`research/extended_direction_landscape_v0.4.md`](research/extended_direction_landscape_v0.4.md)
- [`research/expanded_candidate_directions_v0.4.md`](research/expanded_candidate_directions_v0.4.md)
- [`research/round2_direction_scorecard.csv`](research/round2_direction_scorecard.csv)
- [`research/round2b_direction_scorecard.csv`](research/round2b_direction_scorecard.csv)
- [`research/minimum_gate_plan_v0.4.md`](research/minimum_gate_plan_v0.4.md)
- [`research/novelty_red_lines.md`](research/novelty_red_lines.md)

## 重要边界

- 多数记录仍处于元数据、摘要或官方页面级核验；只有标记为 `full-text-*` 或 `reviewed-full` 的记录可视为完成全文证据提取。
- `literature/frontier_watchlist.csv` 中条目不能替代同行评议证据。
- “未检索到”不等于“文献空白”；任何创新主张仍需完成系统检索、全文核验和最近邻对比。
- 仓库不收录未经许可的付费 PDF。合法全文管理规则见 [`docs/COPYRIGHT_AND_ACCESS.md`](docs/COPYRIGHT_AND_ACCESS.md)。
- 数据集尚未全部下载并固定版本。字段可用性、缺失率、单位和许可必须以实际文件审计为准。
- 半合成网络扩建、队列或行为反馈只能用于门控和机制压力测试，不能替代独立真实验证。
- 研究方向须通过最小门控实验后才能冻结。

## 推荐使用顺序

1. 阅读 [`docs/ROUND2_REVIEW_PROTOCOL.md`](docs/ROUND2_REVIEW_PROTOCOL.md)、[`docs/ROUND2_EXTENSION_PROTOCOL.md`](docs/ROUND2_EXTENSION_PROTOCOL.md) 与 [`docs/ROUND2B_EXTENSION_PROTOCOL.md`](docs/ROUND2B_EXTENSION_PROTOCOL.md)；
2. 查看 [`literature/round2_evidence_matrix.csv`](literature/round2_evidence_matrix.csv) 与 [`literature/round2b_evidence_matrix.csv`](literature/round2b_evidence_matrix.csv)；
3. 按 [`literature/reading_queue.md`](literature/reading_queue.md) 完成 P0 全文审读；
4. 审计 [`datasets/dataset_catalog.csv`](datasets/dataset_catalog.csv) 与 [`datasets/field_audit.csv`](datasets/field_audit.csv)；
5. 执行 [`research/minimum_gate_plan_v0.4.md`](research/minimum_gate_plan_v0.4.md) 中的 Gate S、F、P 和 C；
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
