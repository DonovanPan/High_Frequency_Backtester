

---

# 高频交易做市策略回测系统 (HFT-Backtester)

本项目是一个高性能、端到端的量化交易回测系统，专注于高频（HFT）做市策略。系统通过 Python 实现极致的数据清洗与编译，底层采用 C++ 驱动离散事件模拟，能够精确模拟微秒级的网络延迟、订单簿排队位置以及复杂的微观结构交易逻辑。

## 1. 系统架构图

系统主要由三个核心模块组成，形成一个闭环的数据与策略验证链路：

1.  **数据流水线 (Python ETL)**: 将交易所原始的 L2 深度与逐笔成交数据转换为紧凑的、底层对齐的二进制格式（`.bin`）。
2.  **核心引擎 (C++ Engine)**: 离散事件模拟器。负责维护本地订单簿状态机、模拟撮合队列、执行策略逻辑并计算账户实时损益。
3.  **分析与可视化 (Python Analysis)**: 读取回测生成的交易流水与资金曲线，计算专业量化指标并生成可视化报告。

## 2. 核心功能特性

* **高精度延迟模拟**: 利用最小堆（Priority Queue）管理 `PendingAction`，精确模拟指令发出到交易所生效的往返延迟（RTT）。
* **队列仿真机制**: 引入 `queue_ahead` 指标，真实模拟限价单在交易所撮合池中的排队竞争，避免“见价成交”的过拟合误差。
* **微观结构策略示例**:
    * **OBI (Orderbook Imbalance)**: 实时计算买卖盘力量失衡，识别毒性流量并触发防御性撤单。
    * **库存风控 (Inventory Skewing)**: 根据当前持仓水平动态调整报价偏移（Reservation Price），实现风险中性做市。
* **高性能数据底层**: 使用 `numpy` 结构化数组与 C++ `pragma pack(1)` 结构体实现内存对齐，支持海量 Tick 数据的高速灌入。

## 3. 目录结构

```text
HFT-Backtester/
├── data_pipeline/           # 数据清洗与预处理模块
│   ├── merge.py             # 核心：合并OB与Trades并生成二进制文件
│   ├── extractob.py         # 提取L2订单簿快照
│   ├── extracttrades.py     # 提取并修正时区的逐笔成交
│   └── util/                # 数据探测与校验工具 (opendata.py, readnpz.py)
├── cpp_engine/              # C++ 离散事件回测内核
│   ├── HighFreqBacktester.h # 引擎逻辑与策略状态机
│   ├── Types.h              # 底层数据结构与掩码定义
│   ├── Reporter.h           # 性能评估与CSV导出
│   └── main.cpp             # 引擎运行入口
├── analysis/                # 策略分析与可视化
│   └── plot.py              # 生成权益曲线与回撤报告
└── README.md                # 项目总览
```

## 4. 快速开始指南

### 第一步：环境配置
* **C++**: 需要支持 C++11 或更高标准的编译器（如 GCC 9.0+）。
* **Python**: 3.8+，建议安装 `numpy`, `pandas`, `orjson`, `matplotlib`。

### 第二步：数据编译
将原始的交易所数据（`.tar.gz` 或 `.zip`）放置在指定目录，修改 `merge.py` 中的路径并运行：
```bash
python data_pipeline/merge.py
```
该操作会生成类似 `market_data_2026_01_01.bin` 的文件，这是 C++ 引擎的驱动源。

### 第三步：编译并运行引擎
进入 `cpp_engine` 目录，编译核心引擎并执行：
```bash
g++ -O3 -std=c++11 main.cpp HighFreqBacktester.cpp Reporter.cpp -o hft_engine
./hft_engine
```
引擎运行完毕后，会在当前目录下生成 `equity_curve.csv` 和 `trade_history.csv`。

### 第四步：生成回测报告
运行可视化脚本分析结果：
```bash
python analysis/plot.py
```
系统将输出 `backtest_report.png`，展示包括资金曲线、成交分布及最大回撤在内的详细报告。

## 5. 关键量化指标

引擎通过 `Reporter` 模块自动计算以下指标：
* **年化收益率 (Annualized Return)**
* **年化夏普比率 (Sharpe Ratio)**
* **最大回撤 (Max Drawdown)**
* **卡玛比率 (Calmar Ratio)**
* **日均周转率 (Daily Turnover)**

## 6. 注意事项

* **延迟敏感性**: 该系统对延迟极其敏感。1ms 的模拟延迟差异（如 10ms vs 11ms）可能导致策略从稳定盈利转为持续亏损，这反映了高频竞争的真实残酷性。
* **时区对齐**: 默认 Trades 数据包含 8 小时偏移（UTC+8），系统在 Python 清洗阶段已自动修正为 UTC 时间。

---