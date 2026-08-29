# D0001 ACN-Data Gate 0 获取与语义审计运行手册

## 当前状态

- 官方API与字段文档：已核验；
- 获取脚本与离线单元测试：已实现；
- 真实数据下载：等待研究者本地配置 `ACN_API_TOKEN`；
- Gate 0结论：尚未形成，不能提前声称数据满足正式实验要求。

## 官方接口

- 元数据：`https://ev.caltech.edu/api/v1/sessions/<site_id>`；
- 带时间序列：`https://ev.caltech.edu/api/v1/sessions/<site_id>/ts`；
- 站点：`caltech`、`jpl`、`office001`；
- 身份认证：API token 作为HTTP Basic用户名，密码留空；
- 文档：`https://ev.caltech.edu/dataset`。

官方说明元数据接口分页上限为25个会话，时间序列接口每页1个会话；`/ts`接口开销较大。因此，真实获取按“元数据优先、小样本时间序列、通过后再扩展”的顺序执行。

## 关键语义结论

1. `chargingCurrent` 是EVSE实测电流序列，不是直接的kW有功功率序列；
2. `pilotSignal` 是传给EVSE的导引/控制信号，不能替代实测电流；
3. `disconnectTime`、`doneChargingTime` 和最终 `kWhDelivered` 属于事后结果；
4. `userInputs` 可能多次修改，滚动预测只能使用 `modifiedAt <= issue_time` 的版本；
5. 将电流转换为站级kW，需要进一步固定EVSE电压、相别和网络配置；在此之前不得将电流简单命名为“实测功率”；
6. 2019-10-10以前旧网页下载曾有时区偏移问题，正式数据应通过当前API/Python接口重新获取。

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

### 2. 只检查查询，不访问API

```bash
python scripts/acn_gate0.py download \
  --site caltech \
  --start 2019-05-01T00:00:00-07:00 \
  --end 2019-05-08T00:00:00-07:00 \
  --output data/raw/acn/gate0/caltech_20190501_20190508_metadata.jsonl \
  --max-sessions 500 \
  --dry-run
```

### 3. 下载元数据小样本

删除 `--dry-run`。元数据先用于统计会话量、字段覆盖、时间窗和用户申报字段覆盖率。

### 4. 下载时间序列小样本

```bash
python scripts/acn_gate0.py download \
  --site caltech \
  --start 2019-05-01T00:00:00-07:00 \
  --end 2019-05-08T00:00:00-07:00 \
  --output data/raw/acn/gate0/caltech_20190501_20190508_ts.jsonl \
  --timeseries \
  --max-sessions 50
```

### 5. 执行语义与结构审计

```bash
python scripts/acn_gate0.py audit \
  --input data/raw/acn/gate0/caltech_20190501_20190508_ts.jsonl \
  --output outputs/acn_gate0/caltech_20190501_20190508_audit.json
```

每次下载会产生同名 `.manifest.json`，记录查询条件、记录数、远端总数、完整性状态和SHA-256；manifest不保存token。

## Gate 0最低通过条件

- 能在任一发布时间识别仍在充电的会话；
- 能严格截断至发布时间的电流与pilot序列；
- 时间戳、时区和夏令时处理可复现；
- 不使用未来断开时间、最终充电量和未来用户输入；
- 时间序列长度、单调性和字段覆盖达到可建模要求；
- 明确电流转功率的网络参数来源；
- 控制信号对实测电流的影响可以统计并在论文中说明。

## 停止条件

- API或许可不能支持可复现获取；
- 关键时间序列字段覆盖不足；
- 目标“功率”无法从电流和网络配置可靠恢复；
- 在线信息边界无法建立；
- 结果依赖旧网页下载且时区无法复核。
