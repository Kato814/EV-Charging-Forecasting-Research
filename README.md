# EV-Charging-Forecasting-Research

充电站功率/负荷预测独立研究库。先验证具体预测问题，再确定算法；不以未见城市、未见站点或分布外泛化作为默认论文核心，不混用其他充电站联邦预测项目的方法与结果。

## 唯一当前入口

**当前阶段、运行权限和下一条命令以 [CURRENT_STATUS.md](CURRENT_STATUS.md) 与 [HANDOFF.md](HANDOFF.md) 为准。** 本 README 不再复制阶段性 launcher 或“当前唯一授权”命令，避免概览与真实进度不同步。历史脚本、开放 Issue、旧分支或旧版本 README 的存在，不构成重新执行授权。

| 入口 | 用途 |
| --- | --- |
| [CURRENT_STATUS](CURRENT_STATUS.md) | 当前科学状态与唯一下一步 |
| [HANDOFF](HANDOFF.md) | 接管边界、代码/缓存身份与交付规则 |
| [实验台账](docs/EXPERIMENT_LEDGER.md) | 历史实验、故障修复和结果证据 |
| [数据用途台账](docs/DATA_USAGE_LEDGER.md) | 探索、开发与最终保留集分区 |
| [ROADMAP](ROADMAP.md) | 阶段依赖，不授权运行 |
| [代码说明](code/README.md) | 实现组织与运行保护要求 |
| [开源参考台账](docs/OPEN_SOURCE_IDEA_LEDGER.md) | 成熟实现、相邻工作与创新边界；候选不等于授权 |

## 已接受的研究边界

目标仍为 `station_current_mean_a`，单位 A；不能自行改称已验证 kW 负荷预测。预测负号不构成真实 V2G 证据。

数据用途：已探索 2019-02/05/08/11；方法开发 2019-01/04/07/10；最终独立保留集 2019-03/06/09/12 继续封存。已探索月份不能重新声明为独立 holdout。

冻结强基线 M2 使用历史/日历和当前站级状态；M3 加入当前连接会话的合法细粒度状态。M2/M3 使用已选 HGB 参数和统一同月日级 OOS 规则；其 0.5 简单平均为 Equal 基线。是否允许新实验由独立协议和 CURRENT_STATUS 确定，不从此处推导。

## 结果与协议索引

| 阶段 | 结果或依据 |
| --- | --- |
| 5 月 pilot | PR #21，`PASS_ACTIVE_SESSION_DROP_M4` |
| 季节主实验、消融与组合 | 实验台账；Equal 为强基线 |
| S1 | `MIXED_STRUCTURED_SIGNAL`；实验台账 |
| P1 | [STOP outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)，[已关闭 post-mortem](docs/JPL_P1_A_POSTMORTEM_OUTCOME_20260912.md) |
| R1 | [冻结协议](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)，[MIXED outcome](docs/JPL_R1_JOINT_STATE_OUTCOME_20260912.md) |

这张表是结果索引，不是训练清单。R1 已完成 550 次正式拟合；MIXED 只允许已批准的失败来源分析，不因更换 launcher 或增加日志而重训。

## 资产与版本管理

raw/interim/processed、逐行预测、模型、私有索引、用户/会话标识、凭据和绝对本地路径不提交 Git。所有历史工作树、失败状态、诊断状态与运行后的外置目录保留，不自动清理。

重要变更经独立分支、PR、审查与 CI 后受控合并。代码合并、测试通过、用户本机运行完成与科学假设通过是不同状态。运行版本绑定 reviewed commit；不得仅凭最新分支名执行。

后续耗时脚本须实时显示粗粒度进度、实际耗时与设备。只在批准模型/后端适用时使用 RTX 5080，不为启用 GPU 改变冻结学习器。PowerShell 命令保持单行。

## 维护记录

2026-09-12：移除概览中已经过时的开发专家 v1.2 启动指令及门控开发授权表述，统一由 CURRENT_STATUS/HANDOFF 维护执行权限。历史版本仍在 Git 历史与实验台账中；未删除实验代码、原结果或失败记录。
