# EV-Charging-Forecasting-Research

面向**电动汽车充电功率/负荷预测具体问题、概率预测、会话过程建模、预测—调度闭环及后续可信分布式学习**的长期研究库。

> 当前规划版本：`v0.6.0-closed-loop-plan`  
> 最近核验日期：2026-08-29  
> 状态：研究问题条件锁定；进入数据可行性与最小门控实验阶段；尚未冻结最终论文题目和具体算法。

## 当前主验证方向

> **面向在充会话与未来到达会话双源不确定性的充电站日内滚动概率功率预测。**

在预测发布时刻 \(\tau\)：

\[
P_{\tau+h}=P^{\mathrm{active}}_{\tau+h}+P^{\mathrm{arrival}}_{\tau+h}.
\]

- \(P^{\mathrm{active}}\)：已经接入车辆的剩余充电功率；
- \(P^{\mathrm{arrival}}\)：发布时间之后新到达车辆形成的功率。

两类功率具有不同的信息条件和不确定性来源。当前研究首先检验：会话级实时状态是否具有不可替代的信息增量，以及双源分开建模是否稳定优于强直接聚合模型。

## 完整项目闭环

```text
实时观测
→ 在充会话剩余过程预测 + 未来到达会话预测
→ 站级概率功率/会话需求场景
→ 风险感知滚动调度
→ 执行首时段决策
→ 状态更新并重新预测
```

第一阶段以概率功率预测为主；第二阶段通过小型滚动优化验证运行价值；在预测问题成立后，再扩展车辆级有序充电、预测—决策联合训练和可信联邦学习。

## 当前研究原则

1. 先证明具体预测问题真实存在，再选择复杂模型；
2. 不以未见城市、未见站点或分布外条件代替科学问题；
3. 所有滚动输入必须在预测发布时间真实可获得；
4. 区分请求功率、控制设定功率和实际测量功率；
5. 历史控制策略下的执行功率不得直接解释为自然需求；
6. 概率输出必须评价校准、时间相关性、峰值和爬坡；
7. 预测提升必须通过最小运行价值测试；
8. 任何方向均设置明确停止条件。

## 当前决策文件

- [`research/decision_recommendation_v0.6.md`](research/decision_recommendation_v0.6.md)：研究方向、假设和门控；
- [`research/forecast_dispatch_interface_v0.6.md`](research/forecast_dispatch_interface_v0.6.md)：预测与调度变量接口；
- [`research/execution_roadmap_v0.6.md`](research/execution_roadmap_v0.6.md)：分阶段执行路线；
- [`datasets/acquisition_and_semantics_checklist_v0.6.md`](datasets/acquisition_and_semantics_checklist_v0.6.md)：数据获取与语义审计；
- [`experiments/gate0_gate2_protocol_v0.6.md`](experiments/gate0_gate2_protocol_v0.6.md)：Gate 0–Gate 2 最小实验协议。

历史问题缺口和证据材料继续保留：

- [`research/problem_gap_landscape_v0.5.md`](research/problem_gap_landscape_v0.5.md)
- [`research/evidence_synthesis_v0.5.md`](research/evidence_synthesis_v0.5.md)
- [`literature/round3_evidence_matrix.csv`](literature/round3_evidence_matrix.csv)
- [`research/round3_direction_scorecard.csv`](research/round3_direction_scorecard.csv)

## 下一步

### Phase 0：数据获取与语义审计

1. 获取并固定 ACN-Data 版本；
2. 核验 DESL-EPFL Level 3 数据访问、字段和许可；
3. 建立字段字典、时间戳/时区审计和控制影响审计；
4. 形成预测发布时间字段白名单；
5. 验证会话级功率求和与站级功率的一致性。

### Phase 1：实时状态价值 Gate 1

比较：

1. 历史聚合功率；
2. 聚合功率 + 当前占用率；
3. 聚合功率 + 在充会话摘要；
4. 聚合功率 + 会话部分功率轨迹。

### Phase 2：双源分解价值 Gate 2

比较强直接概率模型、在充分支、未来到达分支、独立双源聚合、相关双源聚合和 oracle 上限。

在 Gate 1–Gate 2 通过前，不开发复杂点过程、扩散模型、可微优化或联邦学习。

## 平行候选与备用方向

1. 弱标签交易数据下的瞬时功率曲线重构；
2. 峰值时刻—幅值—爬坡联合概率预测（低风险备用）；
3. 零负荷激活—会话数量—条件功率复合预测；
4. 控制策略内生性下潜在需求与执行功率分离；
5. 删失条件下潜在、已服务和流失需求；
6. 多时间分辨率一致预测。

## 数据优先级

- **ACN-Data**：主门控数据，重点用于会话窗口、部分轨迹和实时状态；
- **DESL-EPFL Level 3**：独立高分辨率核验，重点区分测量、请求、设定功率和控制状态；
- 其他大规模交易或站级数据：用于弱标签、峰值和广泛验证，不默认具有真实瞬时功率。

## 仓库内容

- 正式同行评议/高可信文献：**67** 篇；
- 前沿观察：**19** 篇；
- 通用及相邻方法基础：**45** 篇；
- 第三轮问题证据：**14** 项，检索簇 **8** 组；
- 候选数据集/仿真器：**15** 个；
- 相关开源仓库：**23** 个；
- 结构化阅读笔记：**37** 份；
- Git版本、校验脚本、Issue模板和代码骨架均保留。

## 重要边界

- “定向检索未发现”不等于文献不存在；
- 不上传无再分发许可的论文 PDF；
- 数据未下载前，字段只视为官方页面级审计；
- 受控执行功率不得直接解释为无控制需求；
- 分布外测试仅作为稳健性证据，不作为当前创新主线；
- 原始数据、模型权重和大型结果不提交到 Git。

## 快速校验

```bash
python scripts/validate_library.py
python scripts/build_reading_queue.py
python -m pytest code/tests
```
