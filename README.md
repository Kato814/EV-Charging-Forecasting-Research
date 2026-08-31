# EV-Charging-Forecasting-Research

面向**电动汽车充电功率/负荷预测具体问题、概率预测、会话过程建模、预测—调度闭环及后续可信分布式学习**的长期研究库。

> 当前规划版本：`v0.7.0-jpl-preflight-pass`  
> 最近核验日期：2026-08-31  
> 状态：研究问题条件锁定；JPL 2019-05当地月元数据门控和100会话时间序列预检通过；完整月时间序列与Gate 1尚未执行。

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

## 计算执行安排

本项目采用：

```text
GitHub / GitHub Actions = 代码、审查和轻量CI控制面
本地Windows + RTX 5080 = 原始数据、正式训练和调度执行面
```

- GitHub Actions只执行仓库校验、Ruff、单元测试、编译检查和CPU小样本冒烟测试；
- ACN Token调用、原始数据处理、完整月聚合、深度模型训练、多随机种子、消融、超参数搜索和调度均在本地工作站运行；
- 当前不购买GitHub GPU runner，也不立即启用self-hosted runner；
- 原始数据、大型中间数组和模型权重不提交Git；GitHub只保存配置、哈希、聚合指标和审计证据；
- 本地GPU环境需通过 `scripts/check_compute_environment.py` 核验后才能执行正式训练。

详细规则：[`docs/COMPUTE_EXECUTION_POLICY.md`](docs/COMPUTE_EXECUTION_POLICY.md)。

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
- [`research/jpl_staged_acquisition_decision_v0.7.md`](research/jpl_staged_acquisition_decision_v0.7.md)：JPL分阶段获取决策；
- [`datasets/acquisition_and_semantics_checklist_v0.6.md`](datasets/acquisition_and_semantics_checklist_v0.6.md)：数据获取与语义审计；
- [`experiments/gate0_gate2_protocol_v0.6.md`](experiments/gate0_gate2_protocol_v0.6.md)：Gate 0–Gate 2最小实验协议；
- [`docs/COMPUTE_EXECUTION_POLICY.md`](docs/COMPUTE_EXECUTION_POLICY.md)：本地GPU与GitHub CI职责边界。

历史问题缺口和证据材料继续保留：

- [`research/problem_gap_landscape_v0.5.md`](research/problem_gap_landscape_v0.5.md)
- [`research/evidence_synthesis_v0.5.md`](research/evidence_synthesis_v0.5.md)
- [`literature/round3_evidence_matrix.csv`](literature/round3_evidence_matrix.csv)
- [`research/round3_direction_scorecard.csv`](research/round3_direction_scorecard.csv)

## 下一步

### Phase 0：完成JPL完整月时间序列与功率语义

1. 获取JPL当地月2019-05的1644个会话及1个carry-in会话的完整 `/ts`；
2. 完成时间序列完整性、重复时间戳、稀疏分钟和边界外电流QA；
3. 固定raw到interim的清洗规则；
4. 验证会话级电流、网络配置与站级功率之间的换算关系；
5. 构造完整连续的15 min站级轨迹和严格截至发布时间的会话快照。

### Phase 1：实时状态价值 Gate 1

比较：

1. 历史聚合功率；
2. 聚合功率 + 当前占用率；
3. 聚合功率 + 在充会话摘要；
4. 聚合功率 + 会话部分功率轨迹。

### Phase 2：双源分解价值 Gate 2

比较强直接概率模型、在充分支、未来到达分支、独立双源聚合、相关双源聚合和oracle上限。

在Gate 1–Gate 2通过前，不开发复杂点过程、扩散模型、可微优化或联邦学习。

## Gate 0代码与证据状态

Gate 0基础设施和JPL 2019-05预检已进入`main`：

- `scripts/acn_gate0.py`：元数据/时间序列有界下载和离线审计；
- `scripts/acn_jpl_2019_05.py`：JPL当地月分块获取入口；
- `evcf.data.acn_api`：带重试、分页、原子写入和SHA-256 manifest的API客户端；
- `evcf.data.acn_audit`：字段覆盖、时序结构、时间边界和泄漏审计；
- JPL当地月元数据：1644个唯一会话，与官方 `_meta.total` 一致；
- 完整历史carry-in：1个；
- 固定种子100会话 `/ts` 预检：100/100匹配，状态PASS；
- `.env.example`：仅声明环境变量名称，不保存真实Token。

重要语义：ACN的`chargingCurrent`是实测电流，不是直接的kW功率。正式功率标签仍需结合EVSE电压、相别和网络配置构造；在完成该步骤前，不得把电流求和直接表述为站级实测功率。

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

- 正式同行评议/高可信文献：**67**篇；
- 前沿观察：**19**篇；
- 通用及相邻方法基础：**45**篇；
- 第三轮问题证据：**14**项，检索簇**8**组；
- 候选数据集/仿真器：**15**个；
- 相关开源仓库：**23**个；
- 结构化阅读笔记：**37**份；
- Git版本、校验脚本、Issue模板和代码骨架均保留。

## 重要边界

- “定向检索未发现”不等于文献不存在；
- 不上传无再分发许可的论文PDF；
- 数据未下载前，字段只视为官方页面级审计；
- 受控执行功率不得直接解释为无控制需求；
- 分布外测试仅作为稳健性证据，不作为当前创新主线；
- 原始数据、模型权重和大型结果不提交到Git。

## 快速校验

```bash
python -m pip install -e .[dev]
python scripts/validate_library.py
python scripts/check_compute_environment.py
python scripts/build_reading_queue.py
python -m pytest code/tests
```

本地RTX 5080正式核验：

```bash
python scripts/check_compute_environment.py --require-cuda --min-vram-gb 14
```
