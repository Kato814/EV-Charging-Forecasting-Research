# 当前状态：主控接管入口

核对日期：2026-09-05。本文是交接快照，不是永久实时状态；执行前读取 [PR #23](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/23) 的最新 HEAD、评论、审查和对应 CI。

## 当前唯一工作

| 项目 | 状态 |
| --- | --- |
| 5月 Gate 1 pilot | 已验收，`PASS_ACTIVE_SESSION_DROP_M4`；PR #21 已合并 |
| 已合并实验基线 | `c2af2cdf4ecf5dad059d2ac92e929df8df35d42b` |
| 季节原始数据 | 2/8/11月已下载；获取集合1289/1509/1354，包含carry-in |
| 季节准备验收 | **阻断：CHANGES_REQUIRED_INVALID_CONTAINER_ACCOUNTING** |
| 在执行分支 | `data/jpl-2019-seasonal-replication` |
| 在执行工作项 | Issue #22 / PR #23；用户已把修订任务交给本地 Codex |
| 上次审查 HEAD | `8c0eeeaff8367dba3c4790de79ba97a018022e0a`，不是修订通过版本 |
| 季节预测模型 | 未运行、未授权 |

## 阻断原因及解除条件

2月2个、11月6个无效 current/pilot 容器会话被整体过滤，未进入后续结构状态与 coverage 分母。它们不同于11月另一个已保留结构状态的3596 s倒退轨迹隔离会话。

修订必须保留元数据正常会话的 connected/arrival/disconnect/carry-in 状态；current/pilot分别记录缺测，不造零、不删掉另一条有效分支。整段 current 不可观测会话所覆盖的15 min格不得作为完整站级总电流正式标签，即使 coverage≥90%。历史输入保留合法缺测mask，离线QA原因不能进入预测特征。

验收依据：[PR #23 review](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/23#pullrequestreview-5120653692)。修订后的代码、测试、前后差异、snapshot、清单和 CI 都要重新核验。**旧 formal 数2439/2784/2524与旧季节 SHA 不是必须复现的新目标。**

## 不可越过的边界

不重下 raw，不修改原始时间戳/manifest，不恢复 M4，不开展概率模型、深度模型、Gate 2、调度或联邦学习，不合并 PR #23 的旧 HEAD。旧 CI 成功仅说明当时测试通过，不代表当前科学审查已解除。

11月合法DST回拨保留2884个物理时间格；异常倒退轨迹不校时。5月原证据不覆盖，8月做数值回归；新溯源信息可以导致新清单哈希变化。

## 新窗口首项动作

先读 [HANDOFF.md](HANDOFF.md)，再读取 PR #23 / Issue #22 最新状态，判断 Codex 是否已提交修订。若仍在运行，仅接管观察和答疑，不重复下达同一任务。修复通过后才冻结下一轮 M2/M3 季节复核协议。
