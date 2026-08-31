# JPL 2019-05 ACN-Data Gate 0 修订与预检

- 数据源：ACN-Data official REST API
- 总体状态：PASS
- 元数据门控：PASS
- 100 会话预检：PASS
- 当地月唯一 sessionID：38 块观测 1644，独立官方 `_meta.total` 1644
- 每日完整块：38/38
- 月份口径：A UTC=1645，B 当地=1644，C 左切片=3，D 右切片=2
- 完整历史 carry-in：1（COMPLETE_INPUT_VALIDATED）

当地月唯一会话数与独立官方 `_meta.total` 一致。

## 100 会话 `/ts` 预检

- 固定种子 201905；匹配 100/100；状态 PASS
- chargingCurrent 覆盖率：1.0
- pilotSignal 覆盖率：1.0
- userInputs 覆盖率：0.97
- 无效容器：current=0，pilot=0
- 重复时间戳：current=1，pilot=1；非单调时间戳：current=0，pilot=0
- 稀疏分钟率：current=0.00577309，pilot=0.00548322
- 采样点保留率：current=0.99517139，pilot=0.99517079
- 会话边界外正电流：86 点 / 28 会话
- 未下载完整月份 `/ts`；在100会话预检后停止，等待主控复核。

## 功率与在线特征语义

- 语义1：chargingCurrent 是实测电流，不是直接 kW。
- 语义2：pilotSignal 是导引或控制信号，不是实测有功功率。
- 语义3：不得简单求和并称为站级有功功率。
- 语义4：由电流转换为功率需要电压、相别、功率因数和网络配置。

disconnectTime、doneChargingTime 与最终 kWhDelivered 是回溯标签；userInputs 也必须按 issue time 截断。
