# 数据用途与独立验证台账

更新：2026-09-08。来源为已审实验协议/结果、月份目录盘点、Issue #29、开发集raw获取及PR #34。此台账用于防止数据重复充当“新验证集”，不自动授权模型训练。

## 1. 已使用月份

| 月份 | 已有用途 | 能否重新声明为独立holdout |
| --- | --- | --- |
| 2019-05 | 基础模型、HGB参数选择、Gate 1 pilot | 否 |
| 2019-02 | 季节主实验、日级/负值诊断、消融、组合 | 否 |
| 2019-08 | 季节主实验、日级/负值诊断、消融、组合 | 否 |
| 2019-11 | 季节主实验、日级/负值诊断、消融、组合 | 否 |

这些月份的旧结果继续有效；不能看过结果并选方法后，再把同一数据包装成新的独立验证。

## 2. 方法开发集：raw已获取，processed准备已授权

固定方法开发集：

```text
2019-01
2019-04
2019-07
2019-10
```

用途：开发和选择Issue #29的可靠性门控器，包括低维门控变量、少量超参数、回退/收缩规则，以及与M2/M3/0.5简单平均的比较。开发集可反复用于方法开发，但不能再称最终独立holdout。

raw获取已验收：

| 月份 | local | carry-in | combined | 有效日块 | QA |
| --- | ---: | ---: | ---: | ---: | --- |
| 2019-01 | 1372 | 0 | 1372 | 31/31 | PASS |
| 2019-04 | 1524 | 0 | 1524 | 30/30 | PASS |
| 2019-07 | 1489 | 0 | 1489 | 31/31 | PASS |
| 2019-10 | 1672 | 1 | 1673 | 31/31 | PASS |

四个月trajectory/full-session quarantine均为0，月级reason_codes为空。冻结metadata源SHA256：

```text
bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

脱敏摘要见 [development_acquisition_20260908.json](../evidence/development_acquisition_20260908.json)。raw获取没有创建processed数据或训练模型。

### 开发集processed协议

PR #34已合并，新增 `code/configs/acn_jpl_development_prep_2019.yaml`。该协议在任何开发集processed结果产生前冻结：

- 月份仅01/04/07/10；
- 清洗、15 min聚合、coverage、24 h lookback、15/30/60/120/240 min horizon及M1–M3特征规则沿用已审单月数值合同；
- 四个月trajectory/full-session quarantine期望均为0，出现新异常即fail-closed；
- 只生成本地ignored interim/processed和脱敏状态，不创建旧02/08/11的37件季节发布；
- 最终holdout 03/06/09/12明确 `access_allowed=false`。

旧 `acn_jpl_seasonal_prep_2019.yaml` 不被改写，继续只代表02/08/11及11月历史特例。

## 3. 最终独立保留集：继续封存

```text
2019-03
2019-06
2019-09
2019-12
```

用途：**仅在方法、输入变量、门控公式/模型、超参数范围、阈值、非负处理、评价指标、统计与停止规则全部冻结后**用于最终独立验证。当前不下载、不准备、不运行模型。

该分区依据月份序号而非预测表现；不因后续某月质量或模型成绩不好就事后换月。若发生数据完整性阻断，只能按预先定义的数据质量停止/缺失处理规则报告，不能结果导向替换。

## 4. metadata候选诊断的正确解释

v1.1获取启动器报告4个结构候选，其中冻结验证通过1个；其余3个同时触发 `SOURCE_LAYOUT` 与 `SOURCE_MANIFEST`。这些是安全拒绝的其他目录，不是开发月份QA失败。最终raw获取状态为 `COMPLETE`，`holdout_accessed=false`。

## 5. 当前授权顺序

1. 现在只允许对01/04/07/10运行PR #34的开发集数据准备；
2. 不重新获取已成功raw；
3. 本地准备完成后先审查raw unchanged、coverage/leakage、M1–M3快照和processed SHA；
4. 审查通过后才进入可靠性门控训练与选择；
5. 03/06/09/12保持封存；方法冻结后单独建立最终holdout Issue再授权。

## 6. 数据质量与独立性原则

目录存在、元数据存在或会话数量正常都不等于时序完整。processed阶段仍必须通过当地月/carry-in、raw保全、缺测结构、15 min coverage、issue-time leakage和快照SHA合同。

开发集可用于门控器选择；最终保留集不得影响方法选择。最终holdout未来即使下载，也不能在方法冻结前查看模型结果或据此调整门控变量/阈值。

## 7. 资产保护与维护

保留用户原main未提交修改、所有登记worktree、raw/interim/processed及三套外置实验目录和private。development raw worktree继续保留；processed准备写入其ignored interim/processed目录，不清理raw。以后新增任何数据用途或查看新结果，主控必须同轮更新本台账、CURRENT_STATUS和HANDOFF。
