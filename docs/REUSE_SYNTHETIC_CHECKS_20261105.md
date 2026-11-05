# 开源复用：独立环境与人工输入工程验证

日期：2026-11-05。状态：**本机工程检查通过；研究有效性尚未验证。**

本轮承接 [PR #114 的资源审计与接口草案](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/114)，在 main `ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c` 上新增独立检查，不依赖该文档 PR 合并。用户已授权继续独立环境和人工输入验证；本轮不执行预测训练、科研数据下载、HVAC 仿真服务或 IEEE 33 节点实验。

## 1. 实际得到什么

| 检查 | 本机结果 | 能说明什么 |
| --- | --- | --- |
| 新环境安装、真实导入、依赖一致性 | Python 3.11.16；pandapower 3.5.6；CVXPY 1.9.3；CLARABEL 0.11.1；`pip check` 通过 | 该组版本可在本机独立环境共同使用 |
| 输入契约 | 拒绝未来可用时间、未知字段、最终 kWh、真实离开时间、非法单位/数值/形状；保留缺测与零的区别 | 校验调用方声明的信息，不能证明其来源和时间戳真实 |
| 单位 | 1000 kW → 1 MW；16 个 15 分钟区间、每段平均 4 kW → 16 kWh | 仅验证已明确为 kW 的算术，不支持将 A/Ah 推定为 kW/kWh |
| 参数化二阶锥小例子 | 理论目标 5、10；实际约 4.999999996、9.999999993；绝对误差均小于 1e-6 | CVXPY 建模、参数更新与 CLARABEL 求解链可用 |
| 故意不可行例子 | `infeasible`，`action: null` | 本例不可行时拒绝输出动作；其他非精确 optimal 状态也不产生有效动作 |
| 人工两节点交流潮流 | 5 kW 时末端电压 0.998698306 pu、网损 6.516955 W；10 kW 时 0.997393205 pu、26.136084 W | 单位和功率符号一致；负荷增加后压降及损耗增加 |
| 功率平衡 | 两例残差约 1.12e-11、1.81e-10 MW，均小于 1e-8 MW | 人工电网的注入、负荷和损耗闭合 |
| 新增测试 | 26 项通过，另含 132 个通过的子用例；Ruff、语法检查通过 | 仅为本轮新增接口与命令的检查 |

原始聚合数值、时间、软件版本和三个执行源码的 SHA256 见 [检查报告](evidence/reuse_synthetic_checks_20261105.json)。测试与旧环境核对见 [验证记录](evidence/reuse_synthetic_validation_20261105.json)。

## 2. 复用方式与环境隔离

本轮使用上游软件包 API，新增薄适配层和自有测试，没有复制第三方完整工程。CVXPY/CLARABEL 为 Apache-2.0、pandapower 为 BSD-3-Clause；版本来源与更完整的适配审计见 PR #114。复用库本身不构成论文创新。

新 venv 禁止继承系统包。NumPy 2.4.6、Pandas 2.3.3、SciPy 1.17.1 与上述组件实际共同导入成功。所安装的 42 个 wheel 的来源 URL 与 SHA256 见 [安装记录](evidence/reuse_synthetic_install_20261105.json)；[版本清单](../requirements-reuse-smoke.lock.txt) 固定本次观测到的 44 个包（包括 venv 自带的 pip、setuptools）。这是一份 Windows x64 / Python 3.11.16 的观测环境清单，不是跨平台通用锁文件，也不是旧预测环境升级指令。

旧环境只查询已安装包的名称和版本。默认环境 398 个包、`evcf-gate1-pilot` 39 个包、`evcf-r2-set` 33 个包，前后完整包元数据列表及其摘要相同。该检查证明包版本元数据未变，不代表对全部安装文件逐字节审计。

## 3. 接口和小例子的边界

- `synthetic-dispatch/v1` 只接收人工预测情景。默认 16 步、每步 900 秒；这是本次样例配置，不冻结论文的时域、最终数据契约或概率模型。没有训练概率预测，也没有把原来的五个预测时距插值成概率轨迹。
- 校验输出是不可变记录；未知字段逐层拒绝；观测可用时间和预测生成时间不得晚于发布时点。没有通过读取真实未来值来模拟在线信息。
- 二阶锥例子为 `min t, ||a||₂ ≤ t`，不含配网、电价、EV 会话、HVAC、储能或风险成本，不能称为配网优化调度已完成。`action` 是例子的目标变量，不能直接执行设备控制。
- 两节点线路、电压和负荷均为手填假设；潮流不是 OPF，也未实施线路容量约束。没有运行 `case33bw`，没有把其占位电流上限认作真实额定值。
- 命令只生成汇总报告，不接收数据或模型路径、不安装依赖、不访问服务；已有输出路径会被拒绝。测试在子进程内拦截 Python socket 连接/DNS 接口后仍完成，属于应用层检查，不是操作系统级断网证明。
- 任一步异常记录为 `FAIL` 并非零退出；数值依赖缺失时，独立命令失败，普通测试明确 skip 对应数值测试。不能把这种 skip 说成数值验证通过。本次数值测试实际执行，未 skip。
- 本例没有测试求解超时策略、紧急回退策略、真实设备约束或求解速度分布。

## 4. 复现入口

从仓库根目录运行。先为本次检查创建全新 Python 3.11 环境，以下每行是独立的 PowerShell 命令；不要用旧预测环境执行安装。若 `.venv-reuse-smoke` 已存在，先确认是本次专用环境，勿覆盖其他环境。

```powershell
py -3.11 -m venv .venv-reuse-smoke
& ./.venv-reuse-smoke/Scripts/python.exe -m pip install --only-binary=:all: -r requirements-reuse-smoke.lock.txt
& ./.venv-reuse-smoke/Scripts/python.exe -m pip check
$env:PYTHONPATH = 'code/src'; & ./.venv-reuse-smoke/Scripts/python.exe -m pytest code/tests/test_reuse_contracts.py code/tests/test_reuse_numerics.py code/tests/test_check_reuse_synthetic_cli.py -q
& ./.venv-reuse-smoke/Scripts/python.exe scripts/check_reuse_synthetic.py --output reuse-synthetic-local.json
```

报告路径必须尚不存在，父目录必须存在；重复检查请选新名称。源码字节哈希受换行符影响，复核归档证据时使用提交中的 LF 内容。上述命令是复现说明，不要求用户现在重复运行。

本机仅运行新增定向测试；未启动旧科研测试或模型 launcher。现有 CI 不安装本轮数值依赖，对应测试应明确 skip；远端 CI 的精确状态在本 PR 交付记录中单独报告，不能用本机通过替代整库 CI。

## 5. 下一阶段的决策门

1. **真实功率语义**：先形成 ACN 字段、仪表口径、电压/相数与可观测时间的映射证据；A→kW 未获依据前，不接入真实充电负荷调度。只读审计不授权新数据获取。
2. **预测与灵活性接口**：定义完整滚动情景轨迹、情景权重、会话可得信息、服务约束及目标评价；旧分区、holdout 和已冻结实验保持原样。新协议另行审阅后才执行。
3. **辅助资源**：继续比较公开 HVAC 与工业负荷资源的控制字段、许可和研究价值。BOPTEST 候选尚未启动，辅助资源仍未定，不因本轮库可运行就宣布 HVAC 已选定。
4. **配网调度**：补齐线路额定值来源，明确线性化 DistFlow/SOCP 的近似与交流回代验收，再实现最小 EV 优化闭环；先验证可行性、服务满足和网络约束，再讨论运行收益。

这些是可调整的后续门槛，不是冻结的最终研究协议。本轮不改变 [CURRENT_STATUS](../CURRENT_STATUS.md)、[HANDOFF](../HANDOFF.md) 的科研状态和执行权限，不改原数据分区、异常规则、封存月份或旧科学结论。PR #114 和本工程 PR 均须明确批准后才可合并。
