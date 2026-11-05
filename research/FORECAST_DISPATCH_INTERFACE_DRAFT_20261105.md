# 预测—灵活性—调度接口草案（开源复用审计）

核对日期：2026-11-05。此文汇总 12 项 EV、10 项 HVAC、12 项网络/优化映射，是拟议接口及来源审计，尚未实现适配器或运行闭环。结论与环境证据见 [审计报告](OPEN_SOURCE_REUSE_AUDIT_20261105.md)。现有冻结协议、station-only 输入边界、数据分区和封存保留集均保持不变；本草案不授权下载、训练、辨识或求解。

## EV 数据与会话接口

核对版本：本仓库 `ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c`；ACN Portal `14e723b11339e56ca3afd2bf4969f9e4bc8c2623`。仅审阅代码和治理文档，未读取数据、私有输出、模型或保留集，未运行任何程序验证科研结果。下表的“已有”指代码能力，不证明字段在实际数据中齐全或通过本轮质量核验。

### 字段映射（12 项）

| 现有字段/入口 | 单位 | 何时可得 | ACN 仿真/调度用途 | 缺口与边界 |
| --- | --- | --- | --- | --- |
| `issue_time_utc_s`、日历字段 [S2](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L270) | UTC 秒、类别 | 发布时间已知 | 对齐仿真起点、15 min 步序和时区 | 适配器需保留 UTC/当地时间与夏令时，不能按行号猜测时间 |
| `station_current_mean_a`、历史 96 格 [S1](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_15min.py#L400)[S2](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L270)[S4](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/forecasting/acn_jpl_r11_s0_data.py#L121) | A | 每个 15 min 区间结束后；快照只截取发布前区间 | 站级预测历史/回放测量基线 | 这是时间加权电流，不能直接作为 kW 或单车功率；区间起始时间戳不等于值的可用时刻 |
| `history_observed_mask`、`observed_coverage_ratio`、`valid_bin_90` [S1](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_15min.py#L400)[S2](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L270) | 布尔、比例 | 对应观测窗口完成后 | 传递缺测和可用性 | 保留冻结质量规则；不可将缺测填零并当作“无车/无负荷” |
| `station_current_a`、`connected_session_count`、`active_charging_session_count` [S2](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L270) | A、个 | 发布时间当前状态；按该时点截断 | 站级负荷/连接状态摘要 | 不是每车能量需求；现行 station-only 推理权限不能从旧 M2/M3 能力反向扩大 |
| `pilot_sum_a`、`current_pilot_a` [S2](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L270) | A | 仅已出现的控制/设定信号 | 说明历史控制状态、核对充电限制 | pilot 不等于实测电流；历史设定不能直接充当未来物理最大功率 |
| `elapsed_connection_s` [S2](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L270) | s | 已连接会话在发布时间的经过时长 | 构造已到站状态、估计剩余连接窗口 | 剩余时间仍需声明/预测；不能由实际未来离站倒推在线状态 |
| `cumulative_current_ah` [S2](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L270) | Ah | 连接至发布时间的已观测积分 | 电流累积状态与覆盖诊断 | Ah 不是 kWh/SOC；缺逐会话实测电压、功率因数及电池信息，不直接填 `EV.energy_delivered` |
| `known_kwh_requested` [S2](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L270) | kWh | 用户记录修改时间不晚于发布时间，且字段确实存在 | 新协议下可作为声明需求候选；再核对总请求/剩余需求语义 | 可空，未核验真实覆盖率；不等于最终交付量；CURRENT_STATUS 禁止进入现行 station-only 推理 |
| `requested_departure_minutes_from_issue` [S2](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L270) | min | 同上，来自当时可见的用户声明 | 新协议下可作为 `estimated_departure` 候选 | 声明不是真实离站；缺失需估计/场景及可靠性处理，不得默认回填真实离站 |
| `labels` / 五时距目标 [S2](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L270)[S4](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/forecasting/acn_jpl_r11_s0_data.py#L121)[S5](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/forecasting/r11_s0_data.py#L34) | A | 对应未来区间完成后 | 离线训练标签、误差评价 | 当前入口为 15/30/60/120/240 min 五目标，不能直接视为 4 h 的 16 步联合概率场景；密集场景接口尚待设计 |
| 实际 `disconnectTime`、最终 `kWhDelivered` [S2](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L270)[A1](https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/events/acndata_events.py#L82) | 时间、kWh | 事后 | 独立离线回放真值/oracle 上限 | 本仓库在线输入黑名单禁止；ACN 默认 `_convert_to_ev` 恰使用这两者，不能原样接在线控制器 |
| `DEFAULT_EVSE_VOLTAGE_V=208`、`energy_at_208v_kwh` [S3](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_power_semantics.py#L46) | V、kWh 候选 | 固定模型参数/离线审计 | 查验 JPL 拓扑及能量一致性 | 代码明确模型默认值不是实测有功功率证据；`e208_authorized=False`、`reconstructed_kw_column_authorized=False`，A→kW 仍须独立审计 |

### 复用结论与尚待设计部分

1. **已有复用基础。** [S3](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_power_semantics.py#L46) 已固定 ACN Portal 同一提交的 JPL 拓扑、BSD-3-Clause、来源及哈希；无需重新建立来源链。现有站级聚合、发布时间截断、质量标记和冻结时间切分可保留，不重写。
2. **关键差距是物理量与信息边界。** ACN 的 [A1](https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/events/acndata_events.py#L82) 默认将最终交付电量当作会话请求、实际离站当作离开时刻；[A2](https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/models/ev.py#L19) 未传 `estimated_departure` 时回退为真实离站。应新增隔离的“控制器可见快照”适配器，仿真器保留真值，控制器只接合法观测、声明或预测。该适配器本轮未实现。
3. **已有快照能力不等于新授权。** M3 可按修改时间提取请求字段，但 [CURRENT_STATUS](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/CURRENT_STATUS.md#L57) 的 station-only 边界保持不变。未来会话调度须另立数据/输入协议；请求覆盖、需求估计、初始 SOC/容量、额定功率及配电网节点映射均尚待核验。
4. **ACN 能复用 EV/电池/桩状态推进与电流容量检查。** [A3](https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/network/charging_network.py#L430) 为聚合电流约束检查，不是完整馈线电压/网损优化；网络模型、联合概率场景、多资源约束、风险成本与运行评价仍需独立模块。代码接通不能宣称这些科学环节已完成。

### 固定版本代码证据

- [S1：15 min 聚合输出，400–427 行](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_15min.py#L400)：时间戳为区间起点；均值、计数及 coverage 口径。
- [S2：快照允许字段，270–340 行](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L270)；[用户输入按修改时间截断，539–548 行](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L539)；[历史与未来标签分离，887–914 行](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L887)；[当前状态/会话积分/声明字段构造，955–1055 行](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_issue_snapshots.py#L955)。
- [S3：已固定 ACN 来源，46–81 行](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_power_semantics.py#L46)；[E208 不授权及在线字段保护，150–215 行](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_power_semantics.py#L150)；[审计输出策略，567–573 行](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/data/acn_jpl_power_semantics.py#L567)。
- [S4：station-only 96 格历史与五目标，121–151 行](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/forecasting/acn_jpl_r11_s0_data.py#L121)。
- [S5：月份白名单及标签合同，34–46 行](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/forecasting/r11_s0_data.py#L34)；[既有时间切分和标签成熟防护，143–188 行](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/code/src/evcf/forecasting/r11_s0_data.py#L143)。
- [A1：ACN 完整会话→EV，82–133 行](https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/events/acndata_events.py#L82)。
- [A2：EV 默认估计离站，19–38 行](https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/models/ev.py#L19)。
- [A3：ChargingNetwork 电流约束与可行性检查，430–541 行](https://github.com/zach401/acnportal/blob/14e723b11339e56ca3afd2bf4969f9e4bc8c2623/acnportal/acnsim/network/charging_network.py#L430)。

治理核对：AGENTS、CURRENT_STATUS、HANDOFF 均已只读复核；JPL `2019-03/06/09/12` 继续封存，当前 R11-P1 判定仍为 MIXED。后续实现/实验需要独立审查，不因本表存在而自动授权。

## HVAC 观测与控制接口

核对日期：2026-11-05。对象：`ibpsa/project1-boptest` 的 `multizone_office_simple_air`。本次仅阅读公开文档、源码与配置；未下载研究数据、FMU 或模型包，未调用部署/仿真 API，未运行模型。本草稿不冻结研究方案或授权实验。

### 1. 固定身份与准备度

- 官方仓库当前默认分支：`master`；本次固定提交：`a29024f8c453517ccbd1186006a3fa6af8de1ae2`（提交时间 2026-10-26T13:47:37Z）。
- 案例是芝加哥商业办公楼中间层、五区域 VAV 再热系统的物理仿真，不是真实办公楼监测数据。模型重点为配风控制；供热/制冷设备具有变效率模型。案例的 Modelica Buildings 依赖另在 `library_versions.json` 固定为 `fe96eca9eb3128702fb6ac1ef5cd69ee985f6207`。[模型说明][hvac-model]、[依赖身份][hvac-libraries]
- **准备度判断：可进入接口设计和后续受控验证准备，尚未达到“已运行通过”或“可直接用于功率调度”的状态。** 已有观测、执行器和预测 API 的文档证据；尚无本机启动、字段回读、控制跟踪、能量对账及降阶模型误差证据。
- 许可为 revised 3-clause BSD **加改进贡献条款**，不是未经附加说明的标准 BSD-3-Clause。保留版权、条件和免责声明；服务层及依赖许可需随实际复用范围登记。[license.md][hvac-license]

### 2. 字段映射（拟议接口，未执行）

区域缩写 `z ∈ {cor,eas,nor,sou,wes}`，测点名称中的区域首字母大写。例如 `Cor`。变量最终名称以固定版本的 `GET measurements/{testid}`、`GET inputs/{testid}`、`GET forecast_points/{testid}` 回读为准，本文没有实际发起这些请求。[模型 I/O][hvac-model]、[API][hvac-api]

| 论文/调度所需变量 | 官方字段或接口 | 单位与映射 | 使用边界 |
| --- | --- | --- | --- |
| 区域室温状态 | `hvac_reaZonCor_TZon_y`；对应 Eas/Nor/Sou/Wes | K；若内部用 ℃，统一减 273.15 | 五区域分别保留，不能用平均温度掩盖单区越界 |
| 当前室外温度 | `weaSta_reaWeaTDryBul_y` | K | 是当前模拟测量；与未来 `TDryBul` 预报区分 |
| 各区舒适温度带 | `LowerSetp[z]`、`UpperSetp[z]`，通过 forecast 获取时间表 | K；生成脚本设占用时 20–24 ℃，非占用时 12–30 ℃ | 舒适带来自场景/时间表；不能拿输入允许范围 285.15–313.15 K 代替舒适带。[时间表生成源码][hvac-setpoints] |
| 区域温度控制设定 | `hvac_oveZonSupCor_TZonHeaSet_u`、`hvac_oveZonSupCor_TZonCooSet_u` 及各区对应字段 | K；公开输入允许范围均为 285.15–313.15 | 每项对应 `*_activate=1` 才覆盖默认控制；自行保证冷热死区及合理设定，不自动等同于室温已满足约束 |
| AHU 送风温度/静压 | `hvac_oveAhu_TSupSet_u`、`hvac_oveAhu_dpSet_u` | K（285.15–313.15）；Pa（50–410） | 与低层控制协调；不能同时随意覆盖不同层控制回路 |
| 风机与阀门执行器 | `hvac_oveAhu_yFan_u`；可选 `hvac_oveAhu_yCoo_u`、`hvac_oveAhu_yHea_u` | 无量纲 0–1，每项有 activate 开关 | 风机值是归一化速度设定而非 kW；初始设计宜保留可解释低层控制，只选择一层监督接口 |
| HVAC 电功率反馈 | `kpis.json` 的七个 `ElectricPower` 分量，见下文 | W → kW 除 1000；能量由功率对时间积分得到 | 核对分量清单与基线负荷边界，避免重计；步末瞬时功率不能直接视作 15 min 平均功率 |
| 天气/占用/内部扰动预测 | `TDryBul`、`HGloHor`、`Occupancy[z]`、`InternalGainsCon/Rad/Lat[z]` 等；`PUT forecast/{testid}` | K、W/m²、人数、W；horizon/interval 均为 s | 默认天气无误差；不确定预报按小时更新，900 s 间隔是小时预报的插值，详见第 4 节 |
| 室内空气质量与通风约束 | `hvac_reaZonCor_CO2Zon_y` 等、`UpperCO2[z]`；区域风量/新风控制另有测点 | ppm、m³/s | 原模型带 CO₂ 与最低新风控制；不能仅靠降风量获得节能而不评价通风服务 |
| 通信步长与滚动时域 | `GET/PUT step/{testid}`，`POST advance/{testid}`；forecast 的 horizon/interval | 案例配置默认 `step=3600.0` s；拟议 15 min 应显式设 900 s；4 h 对应 14400 s | 默认值不是 15 min；通信步长不等于求解器内部积分步长，初始化/预热、首步执行和预报时间戳均须验证。[配置][hvac-config] |

### 3. 功率统计与执行接口

固定版本 [kpis.json][hvac-kpis] 将以下七个不同信号列为 `ElectricPower`：

1. `chi_reaPChi_y`：制冷机电功率；
2. `chi_reaPPumDis_y`：冷冻水分配泵；
3. `heaPum_reaPHeaPum_y`：热泵电功率；
4. `heaPum_reaPPumDis_y`：热水分配泵；
5. `hvac_reaAhu_PFanSup_y`：AHU 送风机；
6. `hvac_reaAhu_PPumCoo_y`：AHU 冷盘管泵；
7. `hvac_reaAhu_PPumHea_y`：AHU 热盘管泵。

拟议 HVAC 电功率取上述清单的一次求和。不能再叠加包含这些分量的系统总功率、把供热/制冷热功率当电功率，或在 IEEE 节点原始基线负荷已含 HVAC 时再次加入。名单是固定版本的统计依据，后续仍应通过物理连接与 KPI 能量对账检查统计边界。其他建筑用电是否计入节点负荷需独立定义；不能把内部热增益（含人员等）直接换算为建筑电负荷。

**优化器输出的整栋功率目标不能直接作为 BOPTEST 输入发送。** 当前已读 I/O 公开的是温度、静压、风机、阀门、风门及泵控制，未提供通用的整栋 kW 功率覆盖输入。拟议架构需要明确选择：

- 监督控制路径：优化器选择区域冷热温度设定或 AHU 监督设定，以降阶动态模型预测相应电功率和室温，交给原低层控制执行。
- 功率计划路径：优化器输出功率计划/预算，由额外的跟踪控制器转成可执行设定；功率跟踪误差必须进入约束或风险评价，不能假定严格跟踪。

两条路径均需在后续获准的验证中辨识或标定降阶模型，并在独立场景回放原模拟器，检验多步温度/功率预测误差、舒适/通风约束、功率跟踪误差和计算时限。本轮没有实施辨识或验证。拟议模型形式、辨识数据范围和阈值尚未冻结。

### 4. 预测与时间边界

官方 [forecast 文档][hvac-forecasts] 和 [forecaster.py][hvac-forecaster] 说明：默认 `temperature_uncertainty=None`、`solar_uncertainty=None`，从仿真边界条件读取确定性预报。若用该默认值，论文必须标明完美/确定性天气假设，不能宣称同时处理了真实天气预报误差。

启用 low/medium/high 后，室外干球温度与 GHI 的不确定预报仅在整点更新；预测时域限制为不超过 48 h，`interval=900` 只将底层 1 h 不确定预报线性插值。拟议 4 h 时域在文档限制以内，但 15 min EV 再预测与小时级天气更新应分别记录。天气误差与 EV 概率场景是两个不同来源，不能互相替代或冒称已经校准其相关性。

案例地点/天气为 Chicago TMY3。与其他站点 EV 数据组合属于构造的协同仿真场景，不能写成真实同址联合观测。未来须明确时区、季节、占用时间表和电价处理；不能只按数组下标拼接。

### 5. 下一步验证门（建议，非本轮执行）

| 门 | 后续需形成的证据 |
| --- | --- |
| 身份与字段 | 固定案例、依赖、API 版本；回读三类字段及单位；确认 900 s 步长、初始化/预热与时间戳 |
| 基线回放 | 原控制器可复现运行，七项电功率/积分能量与 KPI 对账，区域温度和 CO₂ 的约束统计完整 |
| 控制可执行性 | 所选监督设定能合法覆盖、撤回并回到基线；设定上界、舒适带、通风边界分别检查 |
| 降阶与闭环 | 事先规定辨识/验证场景与预算，检验 4 h 多步误差及首步跟踪，不以训练拟合好代替闭环验证 |
| 电网接口 | 使用明确定义的 15 min 平均 kW 与 kWh；核对节点映射、基线负荷排重、无功假设/来源和容量边界 |

真实 Building 59 仍是独立的实测候选：数据许可、代码许可、填补值与在线信息边界尚待审计；它不是本 BOPTEST 案例的现场验证。工业 HIPE 的高频电力记录也不能自动替代生产任务、工序、产量和可中断时长约束；未补齐这些依据前，不将工业灵活性视为已识别。本草稿不扩大辅助资源选择范围。

### 6. 固定版本来源

所有 BOPTEST 链接均固定到本次读取的提交，避免后续 master 漂移；仅链接文档、源码和配置，无数据包。

[hvac-model]: https://github.com/ibpsa/project1-boptest/blob/a29024f8c453517ccbd1186006a3fa6af8de1ae2/testcases/multizone_office_simple_air/doc/index.html
[hvac-api]: https://github.com/ibpsa/project1-boptest/blob/a29024f8c453517ccbd1186006a3fa6af8de1ae2/README.md#restful-http-api
[hvac-kpis]: https://github.com/ibpsa/project1-boptest/blob/a29024f8c453517ccbd1186006a3fa6af8de1ae2/testcases/multizone_office_simple_air/models/kpis.json
[hvac-config]: https://github.com/ibpsa/project1-boptest/blob/a29024f8c453517ccbd1186006a3fa6af8de1ae2/testcases/multizone_office_simple_air/models/config.json
[hvac-setpoints]: https://github.com/ibpsa/project1-boptest/blob/a29024f8c453517ccbd1186006a3fa6af8de1ae2/testcases/multizone_office_simple_air/models/generate_internal_setpoints_data.py
[hvac-forecasts]: https://github.com/ibpsa/project1-boptest/blob/a29024f8c453517ccbd1186006a3fa6af8de1ae2/docs/design/source/forecasts.rst
[hvac-forecaster]: https://github.com/ibpsa/project1-boptest/blob/a29024f8c453517ccbd1186006a3fa6af8de1ae2/forecast/forecaster.py
[hvac-libraries]: https://github.com/ibpsa/project1-boptest/blob/a29024f8c453517ccbd1186006a3fa6af8de1ae2/testcases/multizone_office_simple_air/models/library_versions.json
[hvac-license]: https://github.com/ibpsa/project1-boptest/blob/a29024f8c453517ccbd1186006a3fa6af8de1ae2/license.md

## 网络与优化接口

核对日期：2026-11-05。范围仅为 pandapower 与 CVXPY 的官方稳定发布、依赖、网络静态属性和建模接口。本轮未安装软件、未启动求解器、未运行潮流/预测/优化、未访问实验保留集。case33bw 仅通过 GitHub 文本接口读取并在内存核对结构属性，未将算例文件落盘或安装算例包。

### 1. 采用判断

| 组件 | 判断 | 原因与边界 |
| --- | --- | --- |
| pandapower 网络数据与交流潮流复核 | 条件采用，进入独立环境兼容性检查 | 已有 case33bw 和 runpp；保留自身预测库。必须隔离现有冻结环境；核验 MW/Mvar/kA 与我们的 kW/kWh 接口 |
| case33bw 径向拓扑与阻抗 | 条件采用 | 33 节点、37 个线路记录，其中 32 条投入、5 条退出；静态连接核查为 33 节点连通，32 条投入支路。没有运行潮流 |
| case33bw 默认线路热容量 | **暂缓采用** | 37 条线路 max_i_ka 全部为 99999.0，不能作为有工程依据的热容量；默认 loading_percent 不能证明线路安全 |
| CVXPY 连续凸/SOCP 建模层 | 条件采用，进入独立环境兼容性检查 | 支持 Variable/Parameter/Problem/SOC；它不是求解器，也不自带本论文的完整随机 MPC |
| 多时段 EV/HVAC/储能、风险、非预见性 | 需要自行建模 | 库提供计算设施；场景、物理和信息边界、目标函数、终端条件、滚动执行与评价仍由本项目定义 |
| 整数开停机、充放电互斥或非凸 HVAC | 暂缓具体实现 | 先决定是否确有需要，再选模型及后端。不能默认连续 SOCP 求解器可处理混合整数或一般非凸约束 |

上述判断是工程采用候选，不是科学协议冻结或安装/运行授权。

### 2. 固定的上游版本与来源

GitHub releases/latest 于核对时返回以下正式发布（prerelease=false）；已解析 annotated tag 到 commit，不采用 develop/master 分支作运行版本。

| 项目 | 正式版本 | 发布日期（UTC） | 固定 commit |
| --- | --- | --- | --- |
| pandapower | v3.5.6 | 2026-10-07 | fe517927858f8ffb8ef28db5a15f1a175f57dbbd |
| CVXPY | v1.9.3 | 2026-09-19 | fba7e1f41ca5cf0718918d47d02ba2c3614395d2 |

- [pandapower 发布](https://github.com/e2nIEE/pandapower/releases/tag/v3.5.6)，[固定版本 pyproject](https://github.com/e2nIEE/pandapower/blob/fe517927858f8ffb8ef28db5a15f1a175f57dbbd/pyproject.toml)。
- [CVXPY 发布](https://github.com/cvxpy/cvxpy/releases/tag/v1.9.3)，[固定版本 pyproject](https://github.com/cvxpy/cvxpy/blob/fba7e1f41ca5cf0718918d47d02ba2c3614395d2/pyproject.toml)。
- pandapower [BSD-3-Clause](https://github.com/e2nIEE/pandapower/blob/fe517927858f8ffb8ef28db5a15f1a175f57dbbd/LICENSE)；CVXPY [Apache-2.0](https://github.com/cvxpy/cvxpy/blob/fba7e1f41ca5cf0718918d47d02ba2c3614395d2/LICENSE)。具体后端及第三方算例的来源/许可须另行记录，不能只记录顶层库许可。

### 3. Python 3.11 与最小依赖面

来源为固定版本 pyproject 的核心 dependencies，不包括绘图、文档、性能加速、完整测试及其他可选 extras；这是直接依赖声明，不是已解析或安装成功的环境锁文件。

**pandapower v3.5.6：**

- Python >=3.10（显式列有 Python 3.11）。
- pandas~=2.3。
- networkx~=3.6（Python >=3.11 时）。
- scipy>=1.15；numpy>=1.26,<2.5。
- packaging~=26.0；tqdm~=4.68；colorama==0.4.6。
- deepdiff~=9.1；geojson~=3.3；typing_extensions~=4.16；pandera~=0.32。

**CVXPY v1.9.3：**

- Python >=3.11。
- numpy>=2.0.0；scipy>=1.13.0。
- osqp>=1.0.0；clarabel>=0.5.0；scs>=3.2.4.post1。
- highspy>=1.14.0；qdldl>=0.1.7.post0。
- sparsediffpy>=0.6.0,<0.7.0。
- 从源码构建还声明 setuptools>=68.1.0、wheel、pybind11，以及 NumPy/SciPy 构建依赖；优先核实可用 wheel，避免无意进入本机编译。

**与当前冻结环境的具体冲突：**

[environment-gate1-pilot.yml](https://github.com/Kato814/EV-Charging-Forecasting-Research/blob/ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c/environment-gate1-pilot.yml) 固定 Python=3.11.16、NumPy=2.4.6、pandas=3.0.5、SciPy=1.17.1。pandapower 的 pandas~=2.3 意味着 >=2.3 且 <3.0，和 pandas=3.0.5 冲突；不得直接装进 evcf-gate1-pilot 或为接入新库降低旧实验 pandas。

两库关键声明的交集包含 Python 3.11、NumPy>=2.0,<2.5、SciPy>=1.15、pandas>=2.3,<3.0。当前 NumPy/SciPy 的数值版本落在这些直接约束内，但这不证明完整传递依赖和 Windows wheel 均兼容。建议另建研究优化环境，通过显式数组/文件接口接收预测输出，不改变旧模型环境。Windows/Python 3.11 的 wheel、全部传递依赖及运行稳定性本轮未验证。

### 4. case33bw 静态属性核对

来源：[固定版本 case33bw.json](https://github.com/e2nIEE/pandapower/blob/fe517927858f8ffb8ef28db5a15f1a175f57dbbd/pandapower/networks/power_system_test_case_jsons/case33bw.json)，Git blob SHA：31de24418b0e5fd19806d454653beac4a18e6331。

| 属性 | 核对结果 | 接入要求 |
| --- | --- | --- |
| 节点/线路 | 33 节点；37 条线路记录 | 不把全部线路都纳入径向模型 |
| 投入状态 | 32 条 in_service=true，5 条 false；switch 表为空 | 按 line.in_service 筛选；不能只筛 switch.closed |
| 退出支路 | 索引 32:20→7；33:8→14；34:11→21；35:17→32；36:24→28 | 索引为源文件的零基节点标识；优化器用显式映射，不按显示行号推断 |
| 径向结构 | 32 条投入支路，从 bus 0 可达全部 33 节点 | 这是静态图核查，不是潮流收敛或物理有效性结论 |
| 电压基值 | 全部 vn_kv=12.66 | 三相/相量及标幺约定需固定，避免与 EV 单相测量混用 |
| 系统基值/频率 | sn_mva=10，f_hz=60 | 原样记录；改成其他地区设定须独立说明 |
| 阻抗 | length_km 全部 1.0；r/x 存于 ohm_per_km | 使用 r_ohm_per_km×length_km、x_ohm_per_km×length_km 得到支路总阻抗 |
| 电压边界 | bus 0 的 min/max=1/1，其余 0.9/1.1 pu | 为算例默认值；不能自动替代论文拟采用的运行电压边界 |
| 线路容量 | 所有 max_i_ka=99999.0；max_loading_percent=100 | 99999 kA 不具备已核实的工程容量依据，必须先补参数来源或声明为假设情景 |
| 基础负荷合计 | 3.715 MW、2.300 Mvar | 静态 JSON 求和；不是新实验运行结果 |
| 外部电网 | bus 0，vm_pu=1；P=[0,10] MW、Q=[-10,10] Mvar | 这些是默认优化边界，和购电/反送电政策须分别确定 |

case33bw() 调用 sorted_from_json(...)，其函数说明引用 MATPOWER 来源与 Baran–Wu 1989 算例。[构造函数源码](https://github.com/e2nIEE/pandapower/blob/fe517927858f8ffb8ef28db5a15f1a175f57dbbd/pandapower/networks/power_system_test_cases.py)。

**热容量决策门：**在拿到可追溯的额定电流/容量来源之前，不把默认 loading_percent 低写成“线路安全”。后续可选择有依据的设备参数，或独立声明并做敏感性分析的容量情景；不得伪称它们是原算例的实测线路限值。此门未通过时，可设计电压/损耗接口，但线路越限相关科学结论保持待定。

### 5. 网络—优化字段映射

以下为候选接口，不改变旧数据目标或冻结协议。

| 统一字段/含义 | 来源或目标接口 | 单位及变换 | 权责/检查 |
| --- | --- | --- | --- |
| bus_id、branch_id | net.bus.index；line.index/from_bus/to_bus | 无量纲 ID | 保留源 ID 与优化器连续索引双向映射；只纳入投入支路 |
| delta_t、horizon、scenario_weight | 本项目场景与滚动配置 | 初始候选 0.25 h、16 步；概率非负且归一 | 库不替我们确定时域、场景语义或公平比较规则 |
| p_load、q_load | net.load.p_mw/q_mvar | kW→MW 除以1000；kvar→Mvar 除以1000 | 消耗侧正号；预测 A 不可直接写入 p_mw，须先通过功率语义审计 |
| r_branch、x_branch | line.r_ohm_per_km/x_ohm_per_km×length_km | 欧姆；标幺换算采用一致电压/三相容量基值 | 网络模型与交流复核使用同一套参数 |
| voltage_magnitude / squared_voltage | res_bus.vm_pu；优化变量 v | pu；若 v 表示平方则 v=vm_pu² | 约束边界需同样平方；不能比较 v 与未平方限值 |
| branch_current / squared_current | res_line.i_ka；优化变量 l | kA 或一致标幺；l 表示平方时须明确 | 热容量未就绪；I、I² 与 apparent-power 限值不能混用 |
| active/reactive branch flow | res_line.p_from_mw/q_from_mvar 等 | MW/Mvar；或统一标幺 | 检查 from/to 方向和两端损耗，不将发送/接收端量混为同一量 |
| loss | res_line.pl_mw | MW；时段能量为 MW×h | 源码公式 pl_mw=p_from_mw+p_to_mw；购电已含损耗时避免重复结算 |
| EV/辅助资源/储能功率 | CVXPY Variable；回写对应节点 load/storage | 主接口建议 kW/kWh，网络边界显式转换 | 动态、连接/服务、热状态、SOC 及终端条件由本项目维护 |
| 场景预测、初始状态、电价 | CVXPY Parameter | 固定形状的时段/场景数组，单位随字段声明 | 每轮只更新当时可得信息；禁止把真实未来写成部署输入 |
| 非预见性与首步动作 | 场景共享首步/场景树约束 | 同一发布时间可执行决策一致 | 由本项目实现；不是调用 solve() 自动获得 |
| 电压/电流/服务审计结果 | 网络复核结果与资源状态 | 各自单位、容差、失败状态 | 求解状态、残差、SOCP 间隙、交流回放和服务满足分别报告 |

[固定版本 runpp/runopp](https://github.com/e2nIEE/pandapower/blob/fe517927858f8ffb8ef28db5a15f1a175f57dbbd/pandapower/run.py) 提供潮流与元件表 OPF；[线路结果定义](https://github.com/e2nIEE/pandapower/blob/fe517927858f8ffb8ef28db5a15f1a175f57dbbd/doc/elements/line.rst) 给出损耗及 loading_percent 公式。普通 runpp 是给定注入的潮流计算，不因为元件表里存在限值就自动调整调度满足这些限值。

### 6. CVXPY 接口及后端选择边界

- [SOC 源码](https://github.com/cvxpy/cvxpy/blob/fba7e1f41ca5cf0718918d47d02ba2c3614395d2/cvxpy/constraints/second_order.py)：cp.SOC(t, X, axis=...) 表达二阶锥约束，t/X 维度须一致。DistFlow 的旋转锥需转换成等价标准 SOC 或使用受支持的凸表达，不能直接将变量乘积写入并假设 DCP 会接受。
- [Parameter 源码](https://github.com/cvxpy/cvxpy/blob/fba7e1f41ca5cf0718918d47d02ba2c3614395d2/cvxpy/expressions/constants/parameter.py)：创建问题后可更新数值；适合滚动替换场景、初值和电价。后续检查 is_dcp()/is_dpp()，不把参数化自动等同于可缓存或高性能。
- [固定版本求解器表](https://github.com/cvxpy/cvxpy/blob/fba7e1f41ca5cf0718918d47d02ba2c3614395d2/doc/source/tutorial/solvers/index.rst)：CLARABEL/SCS 支持连续 SOCP；OSQP 为 LP/QP 路线，不能承担本方案的 SOCP；HiGHS 的 LP/QP/MIP 能力不能推导为 MISOCP 能力。
- 初步兼容性检查可优先考虑 CLARABEL，SCS 作为复核候选；具体版本、精度、终止容差及超时策略未冻结。求解器是否可用必须在独立环境验证。
- 采用 mixed-integer 或一般非凸形式时，重新检查后端能力、许可和计算预算；不把当前连续模型的可行性外推。

### 7. 下一步兼容性检查范围（无需真实研究数据）

**本轮已经完成：**固定正式发布与 commit；读取并比对直接依赖；发现 pandas 冲突；核对源文件网络拓扑/默认限值；核对 SOC/Parameter 与后端能力。未运行以下项目。

后续如按独立工程任务启动，可限定为：

1. 在新环境解析两库固定版本依赖和 Windows/Python 3.11 wheel；导出完整锁文件，确认冻结预测环境和代码未变。
2. 仅做导入、版本、已安装求解器清单检查，记录环境标识。
3. 用手写的小数组检查 kW↔MW、节点映射、投入支路筛选、时间轴和场景数组形状，不载入任何 EV/建筑真实数据。
4. 用已知解的微型凸问题检查 SOC、Parameter 更新、DCP/DPP、状态/残差处理；如允许求解，必须单独记录为工程数值检查，不能称为论文实验结果。
5. 以手工两节点网络检查潮流接口和功率方向；33 节点正式算例的导入与潮流试算另列边界，未解决热容量前不得开展或宣称线路安全评价。
6. 模拟不可行/超时状态，验证不把失败写成成功、不执行无效首步动作。随后再决定是否具备进入新科学协议的工程条件。

以上仅是下一步范围建议，本轮未安装、求解或运行。
