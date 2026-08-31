# JPL 2019-05 ACN-Data Phase 1 元数据门控

- 数据源：ACN-Data official REST API
- 门控状态：FAIL
- 分析窗唯一 sessionID：观测 1644，期望 1645
- 每日完整块：38/38
- `/ts` 状态：NOT_RUN，未启动；download_attempted=false

仅凭 1644 与 1645 的计数差异不能定位具体缺失会话。

## 功率与在线特征语义

- 语义1：chargingCurrent 是实测电流，不是直接 kW。
- 语义2：pilotSignal 是导引或控制信号，不是实测有功功率。
- 语义3：不得简单求和并称为站级有功功率。
- 语义4：由电流转换为功率需要电压、相别、功率因数和网络配置。

disconnectTime、doneChargingTime 与最终 kWhDelivered 是回溯标签；userInputs 也必须按 issue time 截断。
