# D0001 ACN-Data Gate 0 获取与语义审计运行手册

## 当前状态

- 官方API与字段文档：已核验；
- 获取脚本与离线单元测试：已实现；
- 网页元数据试验：已完成，详见 `D0001_ACN_METADATA_PILOT_20190501_20190508.md`；
- 网页试验共214个会话，但不含 `chargingCurrent` 或 `pilotSignal`；
- 真实 `/ts` 数据下载：等待研究者本地配置 `ACN_API_TOKEN`；
- Gate 0结论：元数据语义暂时通过，功率轨迹与正式建模窗口尚未通过。

## 官方接口

- 元数据：`https://ev.caltech.edu/api/v1/sessions/<site_id>`；
- 带时间序列：`https://ev.caltech.edu/api/v1/sessions/<site_id>/ts`；
- 站点：`caltech`、`jpl`、`office001`；
- 身份认证：API token 作为HTTP Basic用户名，密码留空；
- 文档：`https://ev.caltech.edu/dataset`。

官方说明元数据接口分页上限为25个会话，时间序列接口每页1个会话；`/ts`接口开销较大。因此，真实获取按“覆盖统计—元数据优先—小样本时间序列—通过后再扩展”的顺序执行。

## 关键语义结论

1. `chargingCurrent` 是EVSE实测电流序列，不是直接的kW有功功率序列；
2. `pilotSignal` 是传给EVSE的导引/控制信号，不能替代实测电流；
3. `disconnectTime`、`doneChargingTime` 和最终 `kWhDelivered` 属于事后结果；
4. `userInputs` 可能多次修改，滚动预测只能使用 `modifiedAt <= issue_time` 的版本；
5. 将电流转换为站级kW，需要进一步固定EVSE电压、相别和网络配置；在此之前不得将电流简单命名为“实测功率”；
6. 2019-10-10以前旧网页下载曾有时区偏移问题，正式数据应通过当前API/Python接口重新获取；
7. 网页导出试验的查询边界以GMT记录，不能默认等于当地日历日边界；正式API查询必须显式提供时区偏移。

## 安全配置

在本地环境变量或PyCharm Run Configuration中设置：

```text
ACN_API_TOKEN=<private token>
```

禁止：

- 在命令行参数中直接传token；
- 将token写入YAML、Python源码、Notebook或Issue；
- 将 `data/raw/` 上传GitHub。

## 推荐执行顺序

### 1. 安装

```bash
python -m pip install -e .[dev]
```

### 2. 先统计逐月覆盖，不下载原始会话

```bash
python scripts/acn_monthly_coverage.py \
  --site caltech \
  --start-month 2018-01 \
  --end-month 2026-08 \
  --timezone America/Los_Angeles \
  --output outputs/acn_gate0/caltech_monthly_coverage.csv
```

输出：

- `caltech_monthly_coverage.csv`：逐月会话数和明确的本地/UTC边界；
- `caltech_monthly_coverage.csv.summary.json`：最新有数据月份、最大月份和最长连续非零区间。

正式训练窗口不能只按“最新”选择。需要同时检查：

- 至少连续12个月；
- 月度会话量足以支持训练与时间后测试；
- 站点/EVSE数量和字段语义没有明显断点；
- `/ts`覆盖能够支撑在充会话轨迹；
- 最后2—3个月可留作严格时间后测试。

### 3. 只检查小样本查询，不访问API

```bash
python scripts/acn_gate0.py download \
  --site caltech \
  --start 2019-05-01T00:00:00-07:00 \
  --end 2019-05-08T00:00:00-07:00 \
  --output data/raw/acn/gate0/caltech_20190501_20190508_metadata.jsonl \
  --max-sessions 500 \
  --dry-run
```

### 4. 下载元数据小样本

删除 `--dry-run`。元数据用于统计会话量、字段覆盖、时间窗和用户申报字段覆盖率。

### 5. 下载时间序列小样本

```bash
python scripts/acn_gate0.py download \
  --site caltech \
  --start 2019-05-01T00:00:00-07:00 \
  --end 2019-05-08T00:00:00-07:00 \
  --output data/raw/acn/gate0/caltech_20190501_20190508_ts.jsonl \
  --timeseries \
  --max-sessions 50
```

### 6. 执行语义与结构审计

```bash
python scripts/acn_gate0.py audit \
  --input data/raw/acn/gate0/caltech_20190501_20190508_ts.jsonl \
  --output outputs/acn_gate0/caltech_20190501_20190508_audit.json
```

每次下载会产生同名 `.manifest.json`，记录查询条件、记录数、远端总数、完整性状态和SHA-256；manifest不保存token。

## 选择正式研究窗口的决策规则

逐月覆盖和 `/ts` 小样本审计完成后，按以下顺序选择正式窗口：

1. 优先选择最新且连续的高质量区间；
2. 训练、验证、测试严格按时间顺序划分；
3. 测试集使用该连续区间中最后2—3个月；
4. 如果最新区间稀疏或字段不完整，则选择较早但连续完整的主窗口，并将最新可用数据作为额外现实性检验；
5. 不把2019年5月试验周默认固定为正式训练数据。

## Gate 0最低通过条件

- 能在任一发布时间识别仍在充电的会话；
- 能严格截断至发布时间的电流与pilot序列；
- 时间戳、时区和夏令时处理可复现；
- 不使用未来断开时间、最终充电量和未来用户输入；
- 时间序列长度、单调性和字段覆盖达到可建模要求；
- 明确电流转功率的网络参数来源；
- 控制信号对实测电流的影响可以统计并在论文中说明；
- 能冻结至少一个连续且足够密集的正式训练—测试区间。

## 停止条件

- API或许可不能支持可复现获取；
- 关键时间序列字段覆盖不足；
- 目标“功率”无法从电流和网络配置可靠恢复；
- 在线信息边界无法建立；
- 结果依赖旧网页下载且时区无法复核。
