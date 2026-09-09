# 当前状态｜充电站功率/负荷预测独立研究

更新日期：2026-09-09。本文件是当前状态唯一入口；历史执行记录见 [实验台账](docs/EXPERIMENT_LEDGER.md)，数据用途见 [数据台账](docs/DATA_USAGE_LEDGER.md)，接管规则见 [HANDOFF](HANDOFF.md)。

**通俗说明：当前已完成方法开发集2019-01/04/07/10的raw获取和processed数据准备，四个月全部PASS。项目正式从“开发集数据准备”进入“模型开发”：下一步先在开发集生成固定M2/M3专家预测并建立强基线，再开发会话信息可靠性门控。最终holdout 2019-03/06/09/12继续封存。**

## 1. 当前研发任务

| 项目 | 当前状态 |
| --- | --- |
| 当前Issue | [#29 基于信息可靠性门控的M2/M3双专家预测](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29) |
| 当前阶段 | **模型开发**；开发集数据准备已完成 |
| 开发集 | 2019-01/04/07/10；raw和processed均已验收 |
| 下一子步骤 | 固定M2/M3开发集专家预测、0.5简单平均基线与可靠性门控开发协议 |
| 模型训练 | 尚未启动本轮开发集模型训练 |
| 最终holdout | **2019-03/06/09/12继续禁止访问** |
| 基础比较 | M2、完整M3、0.5简单平均、可靠性门控 |

## 2. 开发集processed准备已完成

用户回传 `evcf_development_preparation_status_20260909T044544Z.json`：

```text
status = COMPLETE
source status SHA256 = 4573b5e43094ebb8a3c85c71358aac8d93dd3e3926fe9b04366e9fe2a42dd153
code commit = c1ff4e675ae14e7667e0c6b7f887fb15319aff38
protocol SHA256 = 4f2baf0439202bc1db9771a0db530ad9823d9d1261bbcea4c914925beeea5fe1
metadata SHA256 = bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

| 月份 | sessions | bins | valid90 | scheduled/formal | processed snapshot SHA256 | 状态 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 2019-01 | 1372 | 2976 | 2970 | 2865 / 2836 | `e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12` | PASS |
| 2019-04 | 1524 | 2880 | 2772 | 2769 / 2552 | `f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299` | PASS |
| 2019-07 | 1489 | 2976 | 2931 | 2865 / 2742 | `9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2` | PASS |
| 2019-10 | 1673 | 2976 | 2943 | 2865 / 2742 | `e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296` | PASS |

合计：11808个15 min物理格中11616个valid90（98.374%）；11364个scheduled issue中10872个formal（95.671%）。四个月 `raw_unchanged=true`，trajectory/full-session quarantine总数均为0，`holdout_accessed=false`，`models_trained=false`，没有创建旧seasonal public release。

`invalid_skipped_session_count=0` 只表示没有按旧逻辑跳过会话，不用于反推“没有任何无效容器”。

四个月power audit均为 `KW_RECONSTRUCTION_CANDIDATE`，但当前预测目标仍固定为 `station_current_mean_a`（A）；本状态不授权kW预测或功率重构。

去标识化证据见 [development_preparation_20260909.json](evidence/development_preparation_20260909.json)。

## 3. processed故障与修复已收口

首次v1准备失败已由只读诊断定位到 `acn_jpl_gate1_prep.SEASONAL_MONTHS` 兼容绑定遗漏；PR #37仅修复临时开发月白名单并在上下文退出时恢复，不改变科学参数。PR #37最终HEAD `e47f05cb7a663df9c599270ac939c9301d26840b`，main合并 `c1ff4e675ae14e7667e0c6b7f887fb15319aff38`；CI为1058 passed、2 skipped，compileall/Ruff PASS。v1.1实机重试现已完成，故障关闭。

## 4. 当前模型开发方向

M2：24 h历史/日历 + issue-time当前站级聚合状态；M3：M2 + 当前连接会话的合法细粒度状态池化。

现有证据支持M2/M3信息互补，但M3增量价值随预测时距和会话信息可靠性变化。候选方法使用标准MoE/gating范式，但创新主张不放在“动态加权”本身，而放在：

1. 站级状态专家与会话级状态专家的分层信息结构；
2. 仅使用issue-time可得的会话可观测/可靠性变量进行低维门控；
3. 信息不足时向M2可解释回退；
4. 统一因果边界、共同样本和独立holdout验证。

开发阶段至少比较M2、完整M3、0.5简单平均和可靠性门控。若可靠性门控不能在开发集上稳定超过简单平均，或收益依赖高复杂度不可解释调参，则停止该方向，不消耗最终holdout。

## 5. 数据分区继续冻结

- 已使用/探索：2019-02、05、08、11；
- 方法开发集：2019-01、04、07、10；**raw和processed均完成**；
- 最终独立保留集：2019-03、06、09、12；继续封存。

不根据模型结果换月。最终holdout必须等门控变量、模型、超参数、阈值、非负处理、评价、统计和停止规则全部冻结后再单独授权。

## 6. 下一步

1. 主控冻结开发集模型实验协议：仍用HGB M2/M3专家，明确开发集内部训练/验证/评估切分和不泄漏规则；
2. 建立M2/M3开发集预测入口与可复用预测缓存；
3. 先得到M2、M3和0.5简单平均开发基线，再开发可靠性门控；
4. 主控审查开发结果并决定方法是否值得冻结；
5. 只有方法冻结后才允许03/06/09/12进入最终独立验证。

当前不恢复M4，不启动Gate2、概率预测、联邦学习或调度。

## 7. 资产保护与状态维护

保留用户原main未提交修改、所有登记worktree、raw/interim/processed、失败/诊断JSON和三套外置实验目录及其 `local_runs/private`。不执行 `reset --hard`、`clean`、盲目stash或force push。

每次数据准备验收、模型协议冻结、实验完成或结论变化，主控必须同轮更新CURRENT_STATUS、HANDOFF及相关台账，并校对README/ROADMAP/code/README/索引。历史证据通过Git历史、Issue/PR和台账保留。