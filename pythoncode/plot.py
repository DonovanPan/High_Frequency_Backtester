import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

def plot_backtest_results():
    # 1. 读取数据
    try:
        df_equity = pd.read_csv('equity_curve.csv')
        df_trades = pd.read_csv('trade_history.csv')
    except FileNotFoundError:
        print("未找到 CSV 文件，请确保 C++ 引擎已经成功运行并输出了文件。")
        return

    # 转换微秒时间戳为 datetime (UTC)
    df_equity['datetime'] = pd.to_datetime(df_equity['timestamp'], unit='us')
    df_trades['datetime'] = pd.to_datetime(df_trades['timestamp'], unit='us')

    # 计算最大回撤序列用于绘图
    df_equity['max_equity'] = df_equity['equity'].cummax()
    df_equity['drawdown'] = (df_equity['equity'] - df_equity['max_equity']) / df_equity['max_equity'] * 100

    # 2. 准备绘图 (上下两个子图)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 1]})
    fig.suptitle('High Frequency Maker Strategy Backtest', fontsize=16, fontweight='bold')

    # --- 上方子图：资金曲线与买卖点 ---
    ax1.plot(df_equity['datetime'], df_equity['equity'], color='blue', linewidth=1.5, label='Equity Curve')
    
    # 提取买单和卖单
    buys = df_trades[df_trades['side'] == 'BUY']
    sells = df_trades[df_trades['side'] == 'SELL']

    # 映射买卖点到资金曲线上（寻找最近的时间点）
    ax1_price = ax1.twinx()
    ax1_price.plot(df_trades['datetime'], df_trades['price'], color='gray', alpha=0.3, label='BTC Price')
    ax1_price.scatter(buys['datetime'], buys['price'], marker='^', color='green', s=20, label='Buy', zorder=5)
    ax1_price.scatter(sells['datetime'], sells['price'], marker='v', color='red', s=20, label='Sell', zorder=5)
    
    ax1.set_ylabel('Account Equity (USD)', color='blue')
    ax1_price.set_ylabel('BTC Price (USD)', color='gray')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper left')
    ax1_price.legend(loc='upper right')

    # --- 下方子图：回撤 ---
    ax2.fill_between(df_equity['datetime'], df_equity['drawdown'], 0, color='red', alpha=0.3)
    ax2.plot(df_equity['datetime'], df_equity['drawdown'], color='red', linewidth=1)
    ax2.set_ylabel('Drawdown (%)', color='red')
    ax2.set_xlabel('Time (UTC)')
    ax2.grid(True, alpha=0.3)

    # 格式化 X 轴时间显示
    formatter = mdates.DateFormatter('%m-%d %H:%M')
    ax2.xaxis.set_major_formatter(formatter)
    plt.xticks(rotation=45)

    plt.tight_layout()
    plt.savefig('backtest_report.png', dpi=300)
    print("绘图完成！已保存为 backtest_report.png")
    plt.show()

if __name__ == "__main__":
    plot_backtest_results()