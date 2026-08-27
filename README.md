# EV-Charging-Forecasting-Research

面向**电动汽车充电功率/负荷预测具体问题、概率预测、会话过程建模、数据语义审计、预测—调度衔接及后续可信分布式学习**的长期研究库。

> 当前版本：`v0.5.0-problem-gap-review`
> 最近核验日期：2026-08-27
> 状态：完成问题导向的第三轮审查；分布外泛化降为可选验证，不再作为论文核心；尚未冻结最终题目和模型。

## 当前研究逻辑

本仓库不再通过“未见城市、未见站点或更困难划分”制造选题。候选方向必须回答：

1. 充电功率/负荷预测中存在什么具体失败？
2. 最近邻工作已经解决了哪一部分？
3. 遗漏部分是否能由真实可观测数据验证？
4. 复杂模型相对简单基线增加了什么机制价值？
5. 什么结果会否决该方向？

## 当前首要候选

### 在充会话—未来到达双源滚动概率功率预测

在预测发布时刻 \(\tau\)：

\[
P_{\tau+h}=P^{\mathrm{active}}_{\tau+h}+P^{\mathrm{arrival}}_{\tau+h}.
\]

- 第一部分来自已经连接、已有部分功率轨迹的会话；
- 第二部分来自未来尚未到达的随机会话。

现有文献分别研究了剩余占用时间、单车部分曲线、到达事件、bottom-up 概率负荷和联合占用—负荷，但第三轮定向检索尚未确认一个直接最近邻同时完成：合法实时状态条件化、两类来源分开建模、站级概率聚合和源别不确定性解释。该判断仍需全文系统核验。

详见：

- [`research/problem_gap_landscape_v0.5.md`](research/problem_gap_landscape_v0.5.md)
- [`research/evidence_synthesis_v0.5.md`](research/evidence_synthesis_v0.5.md)
- [`research/decision_recommendation_v0.5.md`](research/decision_recommendation_v0.5.md)
- [`research/minimum_gate_plan_v0.5.md`](research/minimum_gate_plan_v0.5.md)
- [`literature/round3_evidence_matrix.csv`](literature/round3_evidence_matrix.csv)
- [`research/round3_direction_scorecard.csv`](research/round3_direction_scorecard.csv)

## 平行候选

1. 弱标签交易数据下的瞬时功率曲线重构与预测；
2. 峰值时刻—幅值—爬坡事件联合概率预测；
3. 零负荷激活—会话数量—条件能量/功率联合分布；
4. 控制策略内生性下潜在充电需求与执行功率分离；
5. 删失条件下潜在、已服务和流失需求；
6. 多时间分辨率一致预测。

## 仓库内容

- 正式同行评议/高可信文献：**67** 篇；
- 前沿观察：**19** 篇；
- 通用及相邻方法基础：**45** 篇；
- 第三轮问题证据：**14** 项，检索簇 **8** 组；
- 候选数据集/仿真器：**15** 个；
- 相关开源仓库：**23** 个；
- 第三轮候选方向：**8** 条；
- Git版本、校验脚本、Issue模板和代码骨架均保留。

## 当前数据优先级

- **ACN-Data**：主门控；具有会话窗口、测量电流和pilot信号；
- **DESL-EPFL Level 3**：外部高分辨率门控；具有P、Pset、Preq、SOC和控制标志；
- 其他大规模交易/站级数据：用于后续弱标签与广泛验证，不默认拥有真实瞬时功率。

## 重要边界

- “定向检索未发现”不等于“文献不存在”；
- 不上传无再分发许可的论文PDF；
- 数据未下载前，字段只视为官方页面级审计；
- 所有滚动预测输入必须在发布时刻可获得；
- 受控执行功率不得直接解释为无控制需求；
- OOD仅作为可选稳健性验证，不作为当前创新主线。

## 推荐使用顺序

1. 阅读 [`docs/ROUND3_PROBLEM_GAP_PROTOCOL.md`](docs/ROUND3_PROBLEM_GAP_PROTOCOL.md)；
2. 查看第三轮证据矩阵和方向评分；
3. 固定ACN与EPFL数据版本并完成字段/控制审计；
4. 执行 `research/minimum_gate_plan_v0.5.md` Gate 1–3；
5. 只有门控通过后，才选择神经生存模型、点过程、条件流或其他骨干；
6. 在 `research/decision_log.md` 中冻结第一个正式实验协议。

## 快速校验

```bash
python scripts/validate_library.py
python scripts/build_reading_queue.py
python -m pytest code/tests
```

## GitHub发布

当前交付仍是完整本地Git仓库。解压后可通过GitHub Desktop发布，或推送到你建立的私有空仓库。详见 [`docs/GITHUB_SETUP.md`](docs/GITHUB_SETUP.md)。
