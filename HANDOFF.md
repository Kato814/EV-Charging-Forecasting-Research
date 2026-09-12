# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-12。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读 [P1 outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)、[P1-A post-mortem outcome](docs/JPL_P1_A_POSTMORTEM_OUTCOME_20260912.md)、[实验台账](docs/EXPERIMENT_LEDGER.md) 与 [open-source idea ledger](docs/OPEN_SOURCE_IDEA_LEDGER.md)。

## 1. 接管结论

S1 正式结论保持 `MIXED_STRUCTURED_SIGNAL`。P1 已按预注册协议正式 `STOP_MECHANISM_ROUTE`：Probe E / A 均为 `NO_COMPONENT_SIGNAL`，P1-EA 不再作为核心预测路线。

P1-A 唯一授权的 read-only post-mortem 已 COMPLETE。它确认 P1-A 的 pooled 数值崩坏高度由极少数 extreme OOS outputs 驱动，最强病理 issue state 为 `2019-10-29 12:00 local`；但 P1-E 也独立失败，因此不能通过修 Poisson、clipping、删除异常 timestamp 或替换单一 branch 来改写 STOP。

G0/S1 已确认的 horizon-dependent composition shift 与 turnover/local-hour 结构继续保留为科学证据。final holdout 2019-03/06/09/12 继续封存。

## 2. 冻结身份

目标：`station_current_mean_a`，单位 A。

Development：2019-01 / 04 / 07 / 10。

Final holdout：2019-03 / 06 / 09 / 12，禁止访问。

Baseline private manifest：`2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd`。

S1 private manifest：`562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1`。

P1 private manifest：`df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f`。

P1 implementation：PR #56；CI-passed head `dac9d18596d8e3ba766e02f83b21d60e650e5957`；merge `33f391c5186650846826fdcb802e4f3e5c329d9d`。

P1-A post-mortem：PR #58；CI-passed head `9bc752f1b416e0dce4cb59942d3ecb07315b9273`；merge `6df5cc836635fedb2034f27cdb34e7dda6e8a885`。

## 3. 冻结基线 / S1 / P1

```text
M2          30.164406 A
M3          29.190188 A
Equal       28.917286 A
S1          28.594882 A
P1-Eonly    30.065656 A
P1-Aonly   172.758507 A
P1-EA      172.966423 A
```

Component MAE：

```text
S1 existing 12.791178 A
P1-E       14.495331 A
S1 arrival 23.105152 A
P1-A      167.857291 A
```

Frozen P1 decisions：

```text
E = NO_COMPONENT_SIGNAL
A = NO_COMPONENT_SIGNAL
P1-EA = STOP_MECHANISM_ROUTE
```

P1-EA：0/5 horizons better than Equal；0/4 months better；60-min MAE 109.278945 A vs Equal 26.141292 A。

## 4. P1-A post-mortem 最终证据

安全审计：

```text
status = COMPLETE
analysis_only = true
model_fit_attempted = false
raw_or_processed_data_accessed = false
holdout_accessed = false
p1_private_cache_unchanged = true
scientific_decision_unchanged = STOP_MECHANISM_ROUTE
```

Across 25,375 development OOS rows：

```text
P1-A MAE       167.857291 A
prediction q50  10.396828 A
prediction q99 518.312153 A
prediction max 2,526,912.316702 A
truth max      742.980111 A
```

Error concentration：

```text
worst 1 row   59.33%
worst 5 rows  81.99%
worst 10 rows 82.09%
worst 1%      84.67%
```

Pathological local issue time `2019-10-29 12:00`：

```text
15 min     1,379.274154 A prediction
30 min 2,526,912.316702 A prediction
60 min   390,526.984821 A prediction
120 min  572,604.896131 A prediction
```

30/60/120 min catastrophic outputs occur at the same issue state. Combined with already passed target reconstruction, row identity and rolling-origin checks, this supports severe OOS extrapolation fragility of the fixed standardized-feature + log-link Poisson count formulation. The private cache lacks predicted counts / linear predictors, so coefficient-level causality is not claimed.

Critically, this does not rescue P1 because Probe E independently worsens pooled component MAE and P1-Eonly is worse than S1/Equal.

## 5. Frozen descriptive mechanism evidence

- existing share falls from 97.38% at 15 min to 26.21% at 240 min；
- future-arrival share rises to 73.79%；
- 30/60 min mixed turnover bins show reproducible weak regions；
- 30/60/120 min near 07:00 are reproducibly weak across months, while 09:00 can reverse direction。

These are mechanism observations, not evidence for continuation×mark, Poisson count×mark, survival, TPP or any specific backbone.

## 6. 当前唯一主线：new-method selection

P1 is closed. Do not continue P1 diagnostics or rescue experiments.

New-method screening must ask:
1. Can the method represent horizon-dependent regime specialization rather than one global rule?
2. Can it capture time-of-day/local-hour state reversal under issue-time legal inputs?
3. Can different horizons use different experts/mechanisms while sharing useful information?
4. Can it avoid unbounded pathological extrapolation without post-hoc test-selected clipping?
5. Can it be evaluated under the same development OOS protocol against M2/M3/Equal/S1?
6. Does the scientific novelty lie in the charging-station forecasting mechanism/problem, rather than merely importing an existing MoE/Transformer/Mamba architecture?

Candidate families may include mixture-of-experts, regime-specialized forecasting and horizon-conditioned routing. Generic backbone replacement alone is insufficient.

Before any new local experiment:
- freeze one precise scientific question;
- identify adjacent/open-source prior art;
- define legal predictors and OOS protocol;
- preregister PASS/MIXED/STOP criteria;
- implement through PR/CI;
- keep final holdout sealed.

## 7. 禁止事项

- no final holdout access；
- no P1 rescue retuning/clipping/calibration；
- no removal of 2019-10 or pathological rows to recalculate P1；
- no automatic pycox/EasyTPP upgrade from failed branches；
- no reliability/composition oracle gate；
- no M2/M3 retuning or development-month reselection；
- no deletion of historical worktrees, failed statuses or private caches；
- no `reset --hard`, `clean`, blind stash or force push。

## 8. 仓库维护

Issue #29、CURRENT_STATUS、HANDOFF、P1 outcome、P1-A post-mortem outcome 与实验台账必须保持一致。新方法建立后应开启新的冻结 protocol/outcome 链路，而不是继续覆盖 P1。
