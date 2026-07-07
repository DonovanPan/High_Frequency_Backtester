import os
import zipfile
import numpy as np
import pandas as pd
import gc
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed

# ==============================================================================
# V2 事件掩码与全局结构体定义
# ==============================================================================
TRADE_EVENT      = 1 << 31  
BUY_SIDE         = 1
SELL_SIDE        = 2
TRADE_BUY_MASK   = TRADE_EVENT | BUY_SIDE
TRADE_SELL_MASK  = TRADE_EVENT | SELL_SIDE

STRUCT_DTYPE = np.dtype([('ev', 'u8'), ('ts', 'i8'), ('px', 'f8'), ('qty', 'f8')])

# ==============================================================================
# 1. Trades 核心处理函数
# ==============================================================================
def process_single_trades_day_task(date_str, zip_path, output_dir):
    output_npz = os.path.join(output_dir, f"trades_{date_str.replace('-', '_')}.npz")
    if os.path.exists(output_npz):
        return f"[{date_str}] 文件已存在，跳过"
    if not os.path.exists(zip_path):
        return f" [{date_str}] 错误：找不到文件 {zip_path}"

    OFFSET_8H_MS = 28_800_000
    
    trades_dtypes = {
        'instrument': str, 'trade_id': str, 'side': str, 'created_time': str,
        'price': np.float64, 'size': np.float64
    }
    
    matrix_list = []
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            csv_files = [f for f in z.namelist() if f.endswith('.csv')]
            if not csv_files:
                return f" [{date_str}] ZIP 内未找到 CSV"
            
            with z.open(csv_files[0]) as f:
                chunk_iter = pd.read_csv(f, dtype=trades_dtypes, chunksize=1_000_000)
                
                for chunk in chunk_iter:
                    raw_ms = pd.to_numeric(chunk['created_time'], errors='coerce').astype(np.int64)
                    ts_micro = (raw_ms + OFFSET_8H_MS) * 1000
                    
                    # 生成掩码数组
                    ev_mask = np.where(chunk['side'].str.lower() == 'buy', TRADE_BUY_MASK, TRADE_SELL_MASK)
                    
                    # 直接分配结构体内存 (与 C++ 完美对齐)
                    chunk_struct = np.empty(len(chunk), dtype=STRUCT_DTYPE)
                    chunk_struct['ev'] = ev_mask.astype(np.uint64)
                    chunk_struct['ts'] = ts_micro.astype(np.int64)
                    chunk_struct['px'] = chunk['price'].astype(np.float64)
                    chunk_struct['qty'] = chunk['size'].astype(np.float64)
                    
                    matrix_list.append(chunk_struct)
        
        if not matrix_list:
            return f" [{date_str}] 无有效数据"

        final_trades = np.concatenate(matrix_list)
        # 按结构体字段 'ts' 进行排序
        final_trades = np.sort(final_trades, order='ts', kind='mergesort')
        
        np.savez_compressed(output_npz, data=final_trades)
        
        count = len(final_trades)
        del final_trades
        del matrix_list
        gc.collect()
        
        return f" [{date_str}] 处理完成，提取 {count} 条记录"

    except Exception as e:
        return f" [{date_str}] 运行时崩溃: {str(e)}"


# 2. 多进程调度主程序
if __name__ == "__main__":
    INPUT_DIR = r"C:\Users\mrp\Desktop\okx trades btc 2026-01\okx trades btc 2026-01"
    OUTPUT_DIR = r"C:\Users\mrp\Desktop\tradesnpz" 
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    tasks = []
    start_date = datetime(2026, 1, 1)
    end_date = datetime(2026, 1, 31)
    
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        zip_filename = f"BTC-USDT-SWAP-trades-{date_str}.zip"
        zip_path = os.path.join(INPUT_DIR, zip_filename)
        tasks.append((date_str, zip_path, OUTPUT_DIR))
        current_date += timedelta(days=1)

    print(f" 准备处理 {len(tasks)} 个任务")
    
    MAX_WORKERS = 5
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_single_trades_day_task, *t): t for t in tasks}
        for future in as_completed(futures):
            print(future.result())

    print("\n Trades 数据清洗全部结束。")