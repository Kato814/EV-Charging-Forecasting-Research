# 主控交付说明｜充电站功率/负荷预测独立研究

更新：2026-09-08。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读本文、[实验台账](docs/EXPERIMENT_LEDGER.md)和[数据用途台账](docs/DATA_USAGE_LEDGER.md)。

## 1. 接管结论

**当前仍处于模型开发阶段，但开发集processed准备首次Windows实机运行未完成。01/04/07/10 raw获取与全月QA已完成且继续有效；本次失败发生在准备链内部，最终holdout未访问、未训练模型。当前只允许只读诊断，不允许直接重跑、删partial输出或改raw。**

当前唯一研发Issue为 [#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。主控负责协议、代码、审查和仓库维护；用户仅执行明确授权的本地Python命令。

## 2. 研究与数据边界

主目标保持 `station_current_mean_a`，单位A。M2=历史/日历+当前站级聚合状态；M3=M2+当前连接会话细粒度合法状态。M4历史负结果保留，不恢复主线。

数据分区固定：
- 已使用/探索：2019-02/05/08/11；
- 方法开发集：2019-01/04/07/10；
- 最终独立保留集：2019-03/06/09/12。

03/06/09/12在门控变量、模型、超参数、阈值、评价和停止规则全部冻结前不得获取时序或运行模型。

## 3. 版本状态

- PR #21已合并：5月pilot；
- PR #23已合并：季节数据/缺测记账；
- PR #30已合并：开发集raw获取入口；
- PR #34已合并：开发集processed准备入口与独立开发协议；最终HEAD `75590bf788712aaad3138367fe9e470b11777644`，main合并 `2643e15a7099b5b25ec0d4f8d22ee4195ac4b6f1`；
- PR #34 CI：1058 passed、2 skipped，compileall和Ruff均PASS。

开发集协议为 `code/configs/acn_jpl_development_prep_2019.yaml`，只绑定01/04/07/10。旧02/08/11季节YAML及11月唯一3596 s例外保持原身份，不扩展到开发月。

## 4. raw开发集已验收

冻结metadata源SHA256：

```text
bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

| 月份 | local | carry-in | combined | 有效日块 | QA |
| --- | ---: | ---: | ---: | ---: | --- |
| 2019-01 | 1372 | 0 | 1372 | 31/31 | PASS |
| 2019-04 | 1524 | 0 | 1524 | 30/30 | PASS |
| 2019-07 | 1489 | 0 | 1489 | 31/31 | PASS |
| 2019-10 | 1672 | 1 | 1673 | 31/31 | PASS |

四个月trajectory/full-session quarantine均为0。

## 5. processed准备首次实机失败

用户运行 `evcf_dev_preparation_launcher_v1.py` 后得到：

```text
status=INCOMPLETE
reason_code=DEVELOPMENT_PREPARATION_INCOMPLETE
preparation_reason_code=UNEXPECTED_ERROR
```

回传状态同时证明：
- 四个月raw preflight继续PASS；
- metadata SHA继续匹配；
- `holdout_accessed=false`；
- `models_trained=false`；
- existing worktrees保持；
- code worktree锁定PR #34合并提交；
- `months=[]`，没有形成已封闭月级准备结果；
- 不能由 `months=[]` 推断完全没有partial interim/processed写入。

当前CLI把未知异常压缩成 `UNEXPECTED_ERROR`，因此尚不能区分“真实数据质量边界”与“准备器未覆盖的真实数据路径”。

## 6. 当前授权：只读诊断

当前只允许运行外置只读诊断工具：
- 复用同一raw和已审代码；
- 读取现有partial输出存在性/文件计数；
- 临时把 `_materialize_local_artifacts` 替换为no-write stub；
- 重放清洗、15 min、issue snapshot、M1–M3特征及验证链；
- 只输出月份、静态reason、异常类型、仓库模块/函数/行号；
- 不写raw/interim/processed，不联网，不训练模型，不访问holdout。

诊断完成后再决定是否需要代码修复或仅补错误分类。

## 7. 方法方向

现有证据支持M2/M3信息互补，M3增量价值随时距和会话信息可靠性变化。候选方法仍是**会话可观测性驱动的低维门控与向M2回退**；普通MoE/动态加权不作为创新。

若开发集上可靠性门控不能稳定超过0.5简单平均，或只能靠高复杂度不可解释调参取得收益，则停止该方向，不消耗最终holdout。

## 8. 资产保护

保留原main未提交修改、所有worktree、raw/interim/processed和三套外置实验目录及 `local_runs/private`。当前尤其不要删除首次失败后可能生成的partial开发集interim/processed，它们是故障定位证据。

禁止 `reset --hard`、`clean`、盲目stash、force push和未经审查的重复运行。

## 9. 下一步

1. 用户执行只读诊断工具；
2. 仅回传脱敏诊断JSON；
3. 主控定位具体异常；
4. 必要时修复代码并重新CI；
5. 重新授权processed准备；
6. processed审查通过后才进入可靠性门控训练。
