# Codebase

正式代码以 Python package 方式组织：

- `evcf.data`：数据读取、schema和无泄漏划分；
- `evcf.forecasting`：点预测、概率预测和场景生成；
- `evcf.evaluation`：准确性、校准、OOD、选择性风险和最差域评价；
- `evcf.flexibility`：后续会话约束、功率/能量边界与可行域；
- `evcf.optimization`：安全基线、oracle价值、学习增强鲁棒调度；
- `evcf.federated`：后续可信联邦实验。

## 第一批代码任务

1. CHARGED 与 UrbanEV 的统一 schema；
2. leave-city/station/zone/time-out 无泄漏划分；
3. seasonal-naive、GBDT、TCN/Transformer 和基础模型基线；
4. 分位数与整轨迹概率评价；
5. 站点支持度、类比检索和选择性预测最小基线；
6. ACN-Sim/EV2Gym 的安全基线与 oracle 调度价值测试。

第一项正式代码任务不是设计新网络，而是冻结数据协议、基线和门控指标。
