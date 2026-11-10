# EV 功率口径与字段接入审计

日期：2026-11-05。结论：**源码和文档映射已完成；真实 kW 接入条件仍未满足。** 本文是可调整的研究工作记录，不是冻结协议或新数据访问授权。

本轮接续 [研究框架及资源审计 PR #114](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/114) 和 [人工工程验证 PR #115](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/115)。只阅读官方资料、固定版本源码和治理文档；未查询 ACN 会话 API、下载研究数据、打开 raw/processed/预测结果或 holdout，也未运行模型、科学实验或新增数值测试。

基线 main：`ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c`；上游 ACN Portal：`14e723b11339e56ca3afd2bf4969f9e4bc8c2623`。可核对的字段表见 [30 项 CSV 映射](ev_dispatch_field_map_20261105.csv)，接入门槛与人工验收用例见 [适配器准入草案](EV_DISPATCH_ADMISSION_DRAFT_20261105.md)，来源身份见 [证据索引](../docs/evidence/ev_power_field_audit_20261105.json)。字段数量是审计条目数，不是实际数据完整率。

## 1. 本轮新增结论

| 已核实事实 | 对接入工作的影响 |
| --- | --- |
| 既有目标 `station_current_mean_a` 是按区间积分定义的 A；时距 h 指向 `[t+h−15min,t+h)`，不是 t+h 瞬时值 | 15/30/60/120/240 min 五列不能直接充当连续 16 步或 4 h 能量预测。[R2][R3] |
| 电流积分为有界前值保持，站级分母为固定 900 s；逐会话 recent mean 分母为已覆盖秒数 | 同为 mean 的字段不能互换；90% coverage 通过不代表缺口已恢复；原口径保持不变。[R1][R2][R3] |
| 事件时间和用户修改时间已存在，实际接收/可用时间证据未在所检 schema 中建立 | 新适配器须区分归档回放假设与实时可得性，不能把 `modifiedAt` 改名 `available_at` 就声称已证明在线无泄漏。[D1][R1][R3] |
| 默认完整会话转换使用最终 `kWhDelivered`、实际 `disconnectTime`，未给估计离站时还会回退到真实离站 | 该转换只适合作为隔离的离线仿真输入；控制器需要独立可见视图。[A1][A4] |
| 上游用 `spaceID` 构造模拟器 station_id | 需要带有效期的设备/停车位/拓扑标签映射，不能把原 `stationID` 与模拟器同名字段直接等同。[A1] |
| 上游拓扑电压、pilot 集合和相别均为模型参数 | 不能据此给历史数据贴上“实测 kW”、设备真实最小电流或真实线路安全标签。[A2][A5][A6] |

## 2. 应保留的既有证据

现有清洗使用左端样本值积分，保持到下一样本、保持上限或截止时刻三者的最早者；保持上限为 `min(3×sampling_mode,60s)`。[R1] 快照 `_prefix_at` 会减去发布时间以后的尾段；没有据此发现使用未来右端电流值的证据。本文不将“存在后续时间戳”写成“历史实验已泄漏”。[R3]

站级电流与 pilot 各自保留 coverage。无连接对象和“有对象但缺测”有不同处理；不能将空值填零冒充真实无负荷。current 目标的冻结质量规则也不能由 pilot 缺失规则替代。[R2][R6]

最终交付量只说明历史策略下已经交付的能量，不等于未受限的真实需求。若把它用作仿真工作量，需要单独声明这一假设；不能据此直接评价真实需求满足率。上游 `force_feasible` 还可能裁剪交付量，适配时须分别保留原始结局和情景修正值。[A1]

历史 station-only 预测边界继续适用；逐会话 current/pilot、请求能量和声明离站不是因为 CSV 出现就获得新的模型输入权限。`e208_authorized=False` 和不授权重构 kW 列的原判断保持原样；候选状态也不等于标定通过。[R4][R5]

## 3. 功率换算究竟缺什么

对一个接口，在同一时间窗、计量边界下，RMS 电压、电流和真实功率因数齐备时，可按物理定义写为：

\[
P_i(t)=V_{i,\mathrm{rms}}(t)I_{i,\mathrm{rms}}(t)\mathrm{PF}_i(t)/1000,
\qquad P_{\mathrm{EVSE\ sum}}(t)=\sum_iP_i(t).
\]

这里的 PF 不是拓扑相别角的余弦；谐波等情况下，单用位移角余弦也不能代替真实功率因数。JPL 模型中的 208 V 是单个跨两相接口的电压；不能额外乘 `√3`，也不能把 EVSE 电流算术和代入平衡三相馈线线电流公式。[A5][A6]

只有显式采用所有接口同为 208 V、PF=1、时间与边界一致等假设时，才有 `P_proxy=0.208×ΣI` kW。该值应标为**假设功率代理量**。上游 `aggregate_power` 用电压与实际 simulated charging_rates 点积，不是 pilot 点积；这证明仿真器的计算定义，不能证明历史有功功率精度。[A3]

15 min 平均功率应由同窗能量或有覆盖规则的功率积分得到；非均匀采样不能简单取样本平均。时变电压/PF 下，平均电流乘一个常数也不等于已测得的平均有功功率。会话 Ah 不能直接抵扣 kWh 请求，最终会话 kWh 也不能反推发布时间已经交付的能量。

## 4. 有用的新数据线索及版本差异

Lee 的 2021 年学位论文第 3 章描述了包含电压、功率、会话累计电量的状态导出，以及并网点聚合功率；后者包含损耗和待机用电。这提供了优先核查计量数据版本的线索，**不证明 legacy API 已包含这些列，也不证明本项目已获得该版本**。[D3]

同一论文的设备表将 AV 最小非零 pilot 记为 8 A，而本次固定 ACN Portal 工厂允许 `{0,6,…,32}` A。它们不是可无条件互换的版本证据。最小非零 pilot 更不是实际电流下限；实际电流或区间均值小于它，不应据此删除。[D3][A2][A7]

官方 legacy 字段页区分测量电流、pilot 和用户声明；其中并没有给出本项目的逐字段接收时间。2019 年论文还说明过两周隐私发布延迟；这是当时的发布背景，不能当作当前固定延迟，也不能把公开归档当实时控制数据源。[D1][D2]

因此，下一份数据版本清单应先核对：格式及发布版本、字段字典、适用站点/年份、计量位置、许可与获取路径。此阶段可继续查元数据；实际获取、样本扫描和标定需要另行明确范围，现有月份分区不调整。

## 5. 接入决定与后续最小工作

1. **保留现有电流研究线。** 使用已冻结 A 目标及原评价，不将旧结果重新命名为已验证 kW 预测。
2. **优先查清计量导出版本。** 若有合法的 Power/累计电量/并网点计量，先核对其定义与覆盖；不存在或证据不足时保持功率门关闭。
3. **先实现可见信息适配层。** 按准入草案先用人工事件测试：迟到、修订、缺测、连接事件、设备映射及事后真值隔离。本文仅交付设计和用例，未声称适配器已实现。
4. **再决定实验配置。** 真实计量、假设功率仿真、归档电流分析分别登记，不能互相替代证据。密集概率轨迹、会话服务约束、辅助资源和网络模型仍需后续协议。

辅助资源仍按公开数据的可用性与研究价值比较 HVAC/工业负荷；本轮不选定资源，也不冻结标题、求解器、时域、模型形式或创新点。所有来源仅用于本轮技术语义核查，不宣称完成相关论文全文评审。

治理：本次只新增文档与字段/来源元数据。main、既有源码、冻结协议、[CURRENT_STATUS](../CURRENT_STATUS.md)、[HANDOFF](../HANDOFF.md)、数据用途及 JPL `2019-03/06/09/12` 保留集均保持不变。PR #115 的旧代码 Ruff 阻断仍是独立问题；本文档检查不能将其 CI 改写成通过。

[R1]: https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_cleaning.py#L470
[R2]: https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_15min.py#L378
[R3]: https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L457
[R4]: https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_power_semantics.py#L150
[R5]: https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/CURRENT_STATUS.md#L57
[R6]: https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/configs/acn_jpl_development_prep_2019.yaml#L41
[A1]: https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/events/acndata_events.py#L102
[A2]: https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/models/evse.py#L12
[A3]: https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/analysis/__init__.py#L18
[A4]: https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/models/ev.py#L35
[A5]: https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/network/charging_network.py#L430
[A6]: https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/network/sites/jpl_acn.py#L12
[A7]: https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/models/battery.py#L45
[D1]: https://ev.caltech.edu/dataset
[D2]: https://ev.caltech.edu/assets/pub/ACN_Data_Analysis_and_Applications.pdf#page=1
[D3]: https://thesis.caltech.edu/14191/1/Lee_Zachary_J_2021_Thesis.pdf#page=49
