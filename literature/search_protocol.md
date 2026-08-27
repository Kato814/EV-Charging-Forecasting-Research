# 文献检索与更新协议

## 1. 当前研究问题域

文献库首先围绕**充电功率/负荷预测中的具体失败**开展检索：

1. 滚动预测发布时，当前在充会话与未来到达会话的信息差异；
2. 到达、停留、需求电量、充电曲线与站级功率的概率聚合；
3. 峰值时刻、峰值幅值、爬坡和阈值越限等运行关键事件；
4. 只有交易电量/时长时的弱标签瞬时功率重构；
5. pilot、setpoint、功率共享和有序充电造成的标签内生性；
6. 零负荷、间歇性、会话数量与连续功率的混合分布；
7. 多时间分辨率预测的一致性及其对峰值/能量的影响；
8. 预测输出对后续功率上限、备用、采购和光储调度的可用性。

分布外泛化、未见城市和未见站点仅作为可选稳健性维度；除非未来研究问题本身转向迁移，否则不作为当前选题依据。

## 2. 数据库

正式检索优先级：

- Web of Science Core Collection；
- Scopus；
- IEEE Xplore；
- ScienceDirect；
- ACM Digital Library；
- SpringerLink；
- Google Scholar：仅用于前后向引文追踪；
- arXiv：仅进入前沿观察库。

## 3. 基础查询块

### A. 领域块

```text
("electric vehicle" OR EV OR e-mobility)
AND ("charging station" OR "charging demand" OR "charging load" OR EVSE)
```

### B. 预测块

```text
(forecast* OR predict* OR "scenario generation" OR probabilistic OR uncertainty)
```

### C. Round 3问题块

```text
("active session" OR "ongoing charging" OR "remaining duration" OR "partial charging curve")
(arrival OR point-process OR queue OR session) AND (power OR load) AND forecast*
("peak timing" OR "peak magnitude" OR ramp OR "threshold exceedance") AND forecast*
("charging profile" OR "power curve") AND (reconstruct* OR weak-label OR energy-duration)
(pilot OR setpoint OR requested-power OR controlled-charging) AND (forecast* OR predict*)
(zero-inflated OR hurdle OR intermittent OR count) AND "charging load"
("temporal reconciliation" OR "multi-resolution") AND (load OR energy) AND forecast*
```

### D. 后续集成块

```text
(flexibility OR schedulable capacity OR load shifting)
(federated OR privacy-preserving OR personalized OR trustworthy)
("decision-focused" OR "predict then optimize" OR differentiable optimization)
("distribution shift" OR "out-of-distribution" OR transfer)  # 仅在需要稳健性/迁移验证时
```

## 4. 时间范围

- 主检索：2019年至今；
- 方法基础：不受时间限制；
- 每月更新前沿观察；
- 每季度重跑正式数据库检索。

## 5. 纳入标准

- 明确预测EV充电功率、需求、占用、会话行为或预测相关决策；
- 对某个具体失败给出可识别的数据、预测发布时信息边界和评价指标；
- 研究问题与所宣称方法一致；
- 对核心方向，优先纳入有公开数据/代码、真实计量、事件级评价或下游运行评价的研究。

## 6. 排除标准

- 只更换模型骨干而未提出具体预测问题；
- 只做优化调度且假设未来充电需求完全已知；
- 只做充电站选址、排队或电池健康，且不含相关预测任务；
- 随机打乱训练/测试导致时间泄漏；
- 把最终会话持续时间、最终电量或充电结束时刻泄漏到滚动预测输入；
- 把额定功率、平均功率或受控执行功率无审计地称为真实需求；
- 无法确定数据来源或评价协议；
- 重复预印本：正式发表后以正式版本为主，预印本只保留代码链接。

## 7. 全文提取要求

每篇全文至少提取：

- 具体预测失败、预测对象、空间层级、时间分辨率和预测时域；
- 预测发布时可获得的输入与未来信息边界；
- 数据集、样本规模、站点类型和功率标签语义；
- 当前会话、未来到达、控制信号和聚合方法；
- 基线、公平性、统计重复和显著性；
- 概率校准、峰值/爬坡/阈值事件或场景质量；
- 下游调度指标；
- 代码/数据许可；
- 最近邻已经解决的部分、剩余缺口和可证伪停止条件。

## 8. 质量评分（0–12）

每项0–2分：

1. 研究问题清晰度；
2. 数据真实性与透明度；
3. 评价协议严谨性；
4. 基线与消融充分性；
5. 可复现性；
6. 与当前具体问题的直接相关度。

评分只用于排序，不替代定性判断。

## 9. 历史轮次

Round 2/2B的OOD、冷启动、可信预测和结构变化检索保留在对应日志与Git历史中，用于约束未来扩展。当前方向以`round3_search_log.csv`和`round3_evidence_matrix.csv`为准。
