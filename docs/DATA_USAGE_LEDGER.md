# 数据用途与独立验证台账

更新：2026-09-09。此台账用于防止数据重复充当“新验证集”，不自动授权模型训练。

## 1. 已使用月份

| 月份 | 已有用途 | 能否重新声明为独立holdout |
| --- | --- | --- |
| 2019-05 | 基础模型、HGB参数选择、Gate 1 pilot | 否 |
| 2019-02 | 季节主实验、日级/负值诊断、消融、组合 | 否 |
| 2019-08 | 季节主实验、日级/负值诊断、消融、组合 | 否 |
| 2019-11 | 季节主实验、日级/负值诊断、消融、组合 | 否 |

## 2. 方法开发集：raw与processed均已完成

固定开发集：

```text
2019-01
2019-04
2019-07
2019-10
```

用途：开发和选择Issue #29的M2/M3可靠性门控器、少量超参数、回退/收缩规则，并与M2、完整M3、0.5简单平均比较。开发集可以用于方法开发，但不能再称最终独立holdout。

processed准备完成身份：

```text
source status SHA256 = 4573b5e43094ebb8a3c85c71358aac8d93dd3e3926fe9b04366e9fe2a42dd153
code commit = c1ff4e675ae14e7667e0c6b7f887fb15319aff38
protocol SHA256 = 4f2baf0439202bc1db9771a0db530ad9823d9d1261bbcea4c914925beeea5fe1
metadata SHA256 = bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

| 月份 | valid90 / bins | formal / scheduled | snapshot SHA256 | 状态 |
| --- | ---: | ---: | --- | --- |
| 2019-01 | 2970 / 2976 | 2836 / 2865 | `e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12` | PASS |
| 2019-04 | 2772 / 2880 | 2552 / 2769 | `f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299` | PASS |
| 2019-07 | 2931 / 2976 | 2742 / 2865 | `9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2` | PASS |
| 2019-10 | 2943 / 2976 | 2742 / 2865 | `e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296` | PASS |

四个月raw unchanged、trajectory/full-session quarantine均0，未训练模型，holdout未访问。去标识化证据见 [development_preparation_20260909.json](../evidence/development_preparation_20260909.json)。

## 3. 最终独立保留集：继续封存

```text
2019-03
2019-06
2019-09
2019-12
```

仅在方法、门控输入、模型结构、超参数范围、阈值、非负处理、评价指标、统计与停止规则全部冻结后用于最终独立验证。当前不下载、不准备、不运行模型。

分区依据月份序号而非预测表现；不因开发结果或未来某月模型成绩不好而换月。

## 4. 当前授权顺序

1. 开发集processed已完成，不再重复准备；
2. 主控先冻结开发集M2/M3专家预测协议和内部开发切分；
3. 用户随后只在明确授权下运行开发集专家预测；
4. 主控先审M2/M3/0.5简单平均，再开发可靠性门控；
5. 方法冻结后另建最终holdout授权；
6. 03/06/09/12在此之前继续封存。

## 5. 数据质量与独立性原则

开发阶段所有比较使用相同有效样本和issue-time可得信息。不能因为4月formal率较低或某些日期难预测而事后删月/删日；数据质量排除只能依据预先固定的质量规则，不能依据预测成绩。

四月power audit均为 `KW_RECONSTRUCTION_CANDIDATE`，但当前目标仍为 `station_current_mean_a`（A），不据此扩展到kW预测。

`invalid_skipped_session_count=0` 不等价于“无无效容器”；只表示结构保留合同下没有跳过会话。

## 6. 资产保护与维护

保留原main未提交修改、所有worktree、raw/interim/processed、失败/诊断JSON和外置实验目录。processed开发数据现在是后续模型开发资产，不清理、不重建。任何数据用途、方法冻结或新结果变化都需同轮更新本台账、CURRENT_STATUS和HANDOFF。
