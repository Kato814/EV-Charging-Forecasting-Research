# Codebase

正式代码以Python package方式组织：

- `evcf.data`：数据读取、schema和无泄漏划分；
- `evcf.forecasting`：点预测、概率预测和场景生成；
- `evcf.flexibility`：会话约束、功率/能量边界与可行域；
- `evcf.optimization`：日前/日内调度和oracle价值测试；
- `evcf.evaluation`：准确性、校准、OOD、可行性和regret；
- `evcf.federated`：后续可信联邦实验。

第一项代码任务不应是新模型，而应是：

1. 数据schema；
2. 时间/站点/城市无泄漏划分；
3. seasonal-naive与GBDT基线；
4. oracle调度价值测试。
