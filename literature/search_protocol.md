# 文献检索与更新协议

## 1. 研究问题域

文献库围绕六个相互关联但不可混淆的域：

1. 充电功率/需求/占用率预测；
2. 会话级到达、离站、能量与充电曲线预测；
3. 概率预测、场景生成与校准；
4. 跨站点、跨城市、跨时间分布外泛化；
5. 充电灵活性预测及其物理/层级一致性；
6. 可信联邦学习及预测—优化耦合。

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

## 3. 查询块

### A. 领域块

```text
("electric vehicle" OR EV OR e-mobility)
AND ("charging station" OR "charging demand" OR "charging load" OR EVSE)
```

### B. 预测块

```text
(forecast* OR predict* OR "scenario generation" OR probabilistic OR uncertainty)
```

### C. 专题块（分别检索，避免一次查询过窄）

```text
(spatiotemporal OR graph OR transformer OR foundation model)
(flexibility OR schedulable capacity OR load shifting)
("distribution shift" OR "out-of-distribution" OR "domain generalization" OR transfer)
(federated OR privacy-preserving OR personalized OR trustworthy)
("decision-focused" OR "predict then optimize" OR differentiable optimization)
(session OR arrival OR departure OR dwell OR charging duration)
```

## 4. 时间范围

- 主检索：2019年至今；
- 方法基础：不受时间限制；
- 每月更新前沿观察；
- 每季度重跑正式数据库检索。

## 5. 纳入标准

- 明确预测EV充电功率、需求、占用、会话行为、灵活性或预测相关决策；
- 给出可识别的数据、划分方式和评价指标；
- 研究问题与所宣称方法一致；
- 对核心方向，优先纳入有公开数据/代码、跨站/跨时测试或下游决策评价的研究。

## 6. 排除标准

- 只做优化调度且假设未来充电需求完全已知；
- 只做充电站选址、排队或电池健康，且不含相关预测任务；
- 随机打乱训练/测试导致时间泄漏；
- 无法确定数据来源或评价协议；
- 重复预印本：正式发表后以正式版本为主，预印本只保留代码链接。

## 7. 全文提取要求

每篇全文至少提取：

- 预测对象、空间层级、时间分辨率和预测时域；
- 可用输入与部署时可获得性；
- 数据集、样本规模、站点类型和地理范围；
- 时间/站点/城市划分，是否严格OOD；
- 基线、公平性、统计重复和显著性；
- 概率校准或场景质量；
- 下游调度指标；
- 代码/数据许可；
- 可复现性和主要局限。

## 8. 质量评分（0–12）

每项0–2分：

1. 研究问题清晰度；
2. 数据真实性与透明度；
3. 评价协议严谨性；
4. 基线与消融充分性；
5. 可复现性；
6. 与本研究问题的直接相关度。

评分只用于排序，不替代定性判断。

## 9. 第二轮相邻方法检索块

为避免只在 EV 领域内部重复模型组合，以下查询块单独检索：

```text
("time series forecasting" AND ("out-of-distribution" OR "domain generalization" OR "environment inference"))
("time series" AND conformal AND (shift OR support OR selective OR abstain*))
("time series foundation model" AND ("in-context" OR retrieval OR "few-shot" OR "zero-shot"))
("EV charging" AND (censor* OR latent demand OR queue OR abandonment OR competition))
((forecast* OR prediction) AND ("learning-augmented" OR "decision-focused" OR "in the loop") AND schedul*)
("EV charging" AND (causal OR incentive OR tariff OR intervention OR policy-conditioned))
("federated time series forecasting" AND (heterogeneous OR calibration OR privacy OR attack))
```

第二轮检索的具体来源、估计筛选量和阶段判断见 `round2_search_log.csv`。通用方法文献的作用主要是**否定宽泛创新表述并确定必须超过的基线**，不能替代 EV 场景实证。
