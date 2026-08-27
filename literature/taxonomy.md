# 文献分类体系

## 预测对象

- `station_power`：站级有功功率或电量曲线；
- `occupancy`：充电桩占用或可用数量；
- `session_arrival`：未来会话数和到达时刻；
- `session_duration/departure`：停留、充电完成或离站；
- `session_energy`：单次需求电量；
- `within_session_profile`：单次充电功率—SOC曲线；
- `flexibility_set`：可调功率/能量边界或可行域；
- `decision_value`：预测对调度、市场、容量或风险的价值。

## 泛化场景

- `temporal_shift`：跨季节、跨年份、行为趋势变化；
- `station_ood`：目标站点完全不进入训练；
- `city_ood`：目标城市完全不进入训练；
- `regime_ood`：价格、天气、节假日或充电策略改变；
- `compositional_ood`：新站点与新运行环境同时出现。

## 不确定性层级

1. 单时点边际区间；
2. 多时段联合轨迹；
3. 多站点层级一致场景；
4. 会话集合分布；
5. 灵活性可行域分布；
6. 下游决策风险。

## 方法类别

- 统计/机器学习；
- RNN/TCN/Transformer；
- 时空图；
- 生成模型（VAE/GAN/flow/diffusion）；
- 时间点过程与集合模型；
- 概率校准与保形预测；
- 域泛化/迁移/测试时适配；
- 联邦/个性化/鲁棒聚合；
- 可微优化与决策导向学习。
