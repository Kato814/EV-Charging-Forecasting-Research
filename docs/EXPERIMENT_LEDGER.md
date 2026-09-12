# 实验与证据台账

更新：2026-09-12。当前任务见 [CURRENT_STATUS](../CURRENT_STATUS.md)。本台账记录已执行/已审查事实及版本身份；接受交付不等于科学假设通过。

**最新记录见第 9 节：R1 COMPLETE，正式 `MIXED_JOINT_STATE_SIGNAL`。第 7–8 节保留 P1 收口时的历史阶段说明，不代表当前执行授权。**

## 1. 版本与发布状态

- 5月预测实验：PR #21，merge `c2af2cdf4ecf5dad059d2ac92e929df8df35d42b`。
- 季节数据/代码：PR #23；数据准备 `CONDITIONAL_PASS`，11 月 `CURRENT_PROXY_ONLY`，季节 kW 未授权。
- development raw/processed：2019-01/04/07/10 已完成并冻结。
- processed compatibility：PR #37，main `c1ff4e675ae14e7667e0c6b7f887fb15319aff38`。
- M2/M3 OOS experts：PR #41；accepted expert code `e5fe6d0aee9035374b6fb3240d3c5ebe2f1b7df7`（PR #45）。
- S1 structured baseline：PR #47；merge `7e914c1fe73376c720c376f0c12fa226a1082314`。
- cache truth tolerance：PR #48；reviewed head `8853d17c5a567a8458e0f638eec90cd31b0dab82`；merge `0f85508f04e8192ec8c7949a512c488255fa58ef`。
- read-only MIXED diagnostic：PR #52；CI-passed head `63ead204b99b131f2c5634f868582411aad8703b`；merge `6236d3fe451838ffb70ff0a1e3a4fcca9de60841`。
- transition-map diagnostic：PR #53；CI-passed head `cc5da1a3683452bea95ff62501dc27c9c2ab7619`；merge `6464cac561f5a1f0c4f7657a6613537c2c675f61`。
- P1 protocol：PR #54，`docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md`。
- P1 implementation：PR #56；CI-passed head `dac9d18596d8e3ba766e02f83b21d60e650e5957`；merge `33f391c5186650846826fdcb802e4f3e5c329d9d`。
- P1 STOP outcome docs：PR #57；merge `c45baac0180b924f62e7f95186b4f54cd173d283`。
- P1-A read-only post-mortem：PR #58；CI-passed head `9bc752f1b416e0dce4cb59942d3ecb07315b9273`；merge `6df5cc836635fedb2034f27cdb34e7dda6e8a885`。
- 当前方法 Issue：#29。

## 2. 已审工作一览

| 工作 | 执行与技术验收 | 研究结论/限制 |
| --- | --- | --- |
| 5月 pilot | PR #21 | `PASS_ACTIVE_SESSION_DROP_M4` |
| 2/8/11 季节主实验 | 570 次日级拟合 | `MIXED_SEASONAL_EVIDENCE` |
| 负值诊断/会话消融 | 诊断 + 570 次消融 | 单纯置零不足；不支持统一删除整组 |
| 预测组合 | 30 项控制 + 300 次校准拟合 | Equal 为强基线；校准加权未稳定超过 |
| development data prep | 01/04/07/10 | 数据冻结；holdout 未访问 |
| M2/M3 expert protocol | 固定 May HGB 参数、日级 OOS、共同测试行 | 强基线冻结 |
| S1 launcher v1 | 拟合前停止 | `MERGE_COMMIT_NOT_FOUND` |
| S1 launcher v1.1 | 拟合前停止 | `MERGE_COMMIT_NOT_FOUND_AFTER_EXPLICIT_FETCH` |
| S1 launcher v1.2 | 首次进入真实 S1 | `COMMON_ROW_IDENTITY_INVALID` |
| PR #48 | tolerance-only fix | 4e-9 A roundoff PASS；2e-6 A mismatch FAIL |
| S1 launcher v1.3 | COMPLETE，fit_count=550 | `MIXED_STRUCTURED_SIGNAL` |
| MIXED diagnostic | COMPLETE；read-only | binary arrival hurdle 不足 |
| transition-map diagnostic | COMPLETE；read-only | horizon-conditioned turnover + local-hour regime 可复现 |
| P1 mechanism probe | COMPLETE，fit_count=1090 | **`STOP_MECHANISM_ROUTE`** |
| P1-A post-mortem | COMPLETE；read-only | extreme OOS tail localized；STOP unchanged |
| R1 joint-state probe | COMPLETE，fit_count=550 | **`MIXED_JOINT_STATE_SIGNAL`** |

## 3. 冻结开发数据身份

以下保留原转录；7 月正文 SHA 的两位遗漏勘误见第 9.4 节，运行配置未变。

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

```text
source expert protocol SHA256
02c7809f1113aeaf20723030c96006ee0831b20ff219106da7d6968df535d71a

baseline private manifest SHA256
2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd

S1 private manifest SHA256
562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1

P1 private manifest SHA256
df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f
```

Final holdout 2019-03/06/09/12 remains sealed.

## 4. G0 / S1 冻结结构证据

| horizon | existing-session | future-arrival |
| ---: | ---: | ---: |
| 15 min | 97.38% | 2.62% |
| 30 min | 90.61% | 9.39% |
| 60 min | 78.10% | 21.90% |
| 120 min | 56.52% | 43.48% |
| 240 min | 26.21% | 73.79% |

Frozen pooled MAE：

```text
M2    30.1644064624 A
M3    29.1901878199 A
Equal 28.9172859886 A
S1    28.5948815297 A
```

S1 仅 2/4 development months better than Equal，故冻结为 `MIXED_STRUCTURED_SIGNAL`。

最稳定的 failure-map evidence：
- 30 min / arrival share 25–50%：0/4 months better；
- 60 min / arrival share 50–75%：0/4 better；
- 60 min / arrival share 0–25%：4/4 better；
- 30/60/120 min @07:00 跨月偏弱；
- 60/120 min @09:00 可跨月反转为强。

## 5. P1 mechanism probe 正式结果

Pooled MAE：

```text
Equal      28.9172859886 A
S1         28.5948815297 A
P1-Eonly   30.0656560018 A
P1-Aonly  172.7585068069 A
P1-EA     172.9664234476 A
```

Component MAE：

```text
S1 existing 12.7911778671 A
P1-E       14.4953310100 A
S1 arrival 23.1051516907 A
P1-A      167.8572913139 A
```

Decision support：
- E horizon wins = 1/5；E month wins = 0/4；
- A horizon wins = 0/5；A month wins = 0/4；
- P1-EA horizon wins vs Equal = 0/5；
- P1-EA month wins vs Equal = 0/4；
- 60-min P1-EA = 109.278945 A vs Equal = 26.141292 A。

Frozen decisions：

```text
Probe E = NO_COMPONENT_SIGNAL
Probe A = NO_COMPONENT_SIGNAL
P1-EA = STOP_MECHANISM_ROUTE
```

## 6. P1-A read-only post-mortem

Safety：

```text
status = COMPLETE
analysis_only = true
model_fit_attempted = false
raw_or_processed_data_accessed = false
holdout_accessed = false
p1_private_cache_unchanged = true
scientific_decision_unchanged = STOP_MECHANISM_ROUTE
```

Overall P1-A OOS：

```text
n              25,375
MAE            167.857291 A
prediction q50  10.396828 A
prediction q99 518.312153 A
prediction max 2,526,912.316702 A
truth max      742.980111 A
```

Threshold counts：

```text
>100 A    2997
>500 A     280
>1000 A     22
>5000 A      3
>10000 A     3
```

Absolute-error concentration：

```text
worst 1 row   59.33%
worst 5 rows  81.99%
worst 10 rows 82.09%
worst 1%      84.67%
```

Dominant pathological issue state：`2019-10-29 12:00 local`。

```text
15 min      1,379.274154 A prediction
30 min  2,526,912.316702 A prediction
60 min    390,526.984821 A prediction
120 min   572,604.896131 A prediction
```

Interpretation boundary：
- same issue state across multiple horizons + passed target/row/rolling checks support severe OOS extrapolation fragility in the fixed standardized-feature + log-link Poisson count route；
- private cache lacks predicted counts / Poisson linear predictors, therefore no coefficient-level causal claim；
- this cannot rescue P1 because Probe E independently fails and P1-Eonly is worse than S1/Equal。

## 7. P1 收口时的阶段裁决（历史保留）

- S1 remains `MIXED_STRUCTURED_SIGNAL`。
- P1 remains **`STOP_MECHANISM_ROUTE`**。
- P1-A post-mortem is closed；no further P1 rescue diagnostics are authorized。
- descriptive horizon-conditioned turnover evidence remains available for new-method design。
- final holdout remains sealed。

## 8. P1 收口时的下一阶段（历史保留）

进入 **new-method selection**。下一候选需优先处理：
1. horizon-dependent regime specialization；
2. time-of-day/local-hour state reversal；
3. horizon-specific experts/mechanisms under legal issue-time inputs；
4. protection against uncontrolled OOS extrapolation by design rather than test-selected clipping；
5. unified OOS comparison against M2/M3/Equal/S1；
6. novelty must come from the charging-station forecasting mechanism/problem, not generic backbone substitution。

No new local model run is authorized until a new scientific question, protocol and preregistered decision rule are frozen.

## 9. R1 正式运行及聚合审计

### 9.1 版本链

- PR #59：P1 归档，merge `0dbae8be2fa71d870ff89138280e1df583ab7e60`。
- PR #60：post-P1 方法筛选，merge `5c964601e2374d16a341e2c55ec73ec0116731f6`。
- PR #61：R1 protocol，merge `5c56ac71d6e94e6c566e88a855b4f9646eb170ea`。
- PR #62：R1 implementation，reviewed head `e01607078431141a1fccdd6a9db5f75ae561bfda`，merge `0a2f1fc29af3fc6232534c8f6073c276dbe9122f`，全量 CI 通过。
- PR #63：运行前状态同步，merge `436b1da28bb583e0f155deae38ee0bbc4358acf5`。
- 本次 R1：COMPLETE，550 fits，20 private cache files，正式 `MIXED_JOINT_STATE_SIGNAL`。

详细结论见 [R1 outcome](JPL_R1_JOINT_STATE_OUTCOME_20260912.md)。

### 9.2 判据与结果

```text
R1-Control MAE 29.192881902331596 A
R1-Joint MAE   29.039977599163333 A
Equal MAE      28.917285988574830 A
S1 MAE         28.594881529744885 A
```

Joint vs Control：pooled 改善 0.523773%，4/5 horizon wins、3/4 month wins。

Joint vs Equal：pooled 退化 0.424285%，3/5 horizon wins、2/4 month wins。

60 min：Joint 26.086069 A < Equal 26.141292 A；优势仅 0.211249%。最大 horizon 退化为 1.110700%。八项 PASS 条件六项通过；失败的是 pooled 优于 Equal、至少 3/4 月优于 Equal。MIXED 条件成立，STOP 未触发。

### 9.3 已完成的失败来源分析与边界

7 月五个时距 Joint 均差于 Control。10 月 Joint pooled 优于 Control，但未追平 Equal。60 min 仅 1、4 月胜 Equal；120/240 min pooled 差于 Equal。

已按样本数重算 20 个 month-horizon cell 的总体、时距和月度汇总，含 MAE、平方加权 RMSE、WAPE、负预测数，均与 status 一致；decision_support 独立复算一致。状态报告数据/cache 未改，历史 worktree 保留，无 holdout 访问。远程审计未独立访问本机 private cache。

25,375 是合并五时距的 origin-horizon 记录数，不是独立样本量。当前未做显著性检验。小时/日级误差和特征支持度未包含在该 JSON 中，不能从现有聚合表推断。

当前仅允许失败来源分析，不重跑训练、不更换 Pearson、不筛 pair、不做预测后处理或集合网络升级。

### 9.4 7 月 SHA 正文勘误

第 3 节及 R1 protocol 旧正文中的 July SHA 为 62 位，缺少 `c4`。执行前已存在的机器配置、原 launcher 和本次 status 一致使用：

`9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2`

此处追加勘误，保留原文以供追溯，不修改冻结协议、机器配置、数据身份或判据。
