# Codebase

正式代码以 Python package 方式组织：

- `evcf.data`：数据获取、字段语义、在线信息边界、schema和无泄漏划分；
- `evcf.forecasting`：点预测、概率预测和场景生成；
- `evcf.evaluation`：准确性、校准、峰值、爬坡和运行事件评价；
- `evcf.flexibility`：后续会话约束、功率/能量边界与可行域；
- `evcf.optimization`：安全基线、oracle价值和风险感知滚动调度；
- `evcf.federated`：中央方法稳定后的可信联邦实验。

## 当前代码任务：ACN Gate 0

在模型开发前先完成数据与语义门控：

1. 安全获取有界ACN元数据和时间序列；
2. 固定查询窗口、API条件、原始文件SHA-256和下载manifest；
3. 审计会话字段、时间戳、时区、时间序列长度和用户输入覆盖率；
4. 区分`chargingCurrent`、`pilotSignal`和最终会话结果；
5. 构造严格截至发布时间的在线会话快照；
6. 在获取EVSE网络参数前，不把电流序列直接命名为kW功率。

安装：

```bash
python -m pip install -e .[dev]
```

查询预览：

```bash
python scripts/acn_gate0.py download \
  --site caltech \
  --start 2019-05-01T00:00:00-07:00 \
  --end 2019-05-08T00:00:00-07:00 \
  --output data/raw/acn/gate0/pilot_metadata.jsonl \
  --max-sessions 500 \
  --dry-run
```

访问凭据只通过本地环境变量`ACN_API_TOKEN`提供，不得写入仓库。

## Gate 0通过后的代码顺序

1. 严格无泄漏滚动样本构造器；
2. M1–M4实时信息阶梯基线；
3. 简单双源统计/机器学习模型；
4. 概率评分、峰值、爬坡和阈值超越评价；
5. Gate 1–2通过后，再选择神经生存模型、标记点过程或其他深度骨干；
6. 最后进行小型预测—调度运行价值测试。
