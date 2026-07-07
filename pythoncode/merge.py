
import os

import zipfile
import tarfile

import orjson

import pandas as pd

import numpy as np
import logging

from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed

# 配置日志
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(message)s'
)


# V2 事件掩码与全局结构体定义
DEPTH_EVENT      = 1 << 28  # 268435456
TRADE_EVENT      = 1 << 31  # 2147483648
BUY_SIDE         = 1
SELL_SIDE        = 2

DEPTH_BUY_MASK   = DEPTH_EVENT | BUY_SIDE
DEPTH_SELL_MASK  = DEPTH_EVENT | SELL_SIDE
TRADE_BUY_MASK   = TRADE_EVENT | BUY_SIDE
TRADE_SELL_MASK  = TRADE_EVENT | SELL_SIDE

STRUCT_DTYPE = np.dtype([('ev', 'u8'), ('ts', 'i8'), ('px', 'f8'), ('qty', 'f8')])


# 1. 解析 OrderBook，生成结构化数组 
def parse_ob_to_struct(targz_path, depth_limit=20, max_errors=100):
    """解析 L2 深度，返回 NumPy 结构化数组，带有严格的异常捕获"""
    if not os.path.exists(targz_path):
        logging.warning(f"文件不存在: {targz_path}")
        return np.array([], dtype=STRUCT_DTYPE)
    
    events = []
    error_count = 0
    
    with tarfile.open(targz_path, 'r:gz') as tar:
        for member in tar.getmembers():
            if member.isfile():
                f = tar.extractfile(member)
                if f is not None:
                    for line_num, line_bytes in enumerate(f, start=1):
                        line = line_bytes.strip()
                        if not line: continue
                        
                        try:
                            data = orjson.loads(line)
                            if 'ts' not in data:
                                raise KeyError("缺少 'ts' 字段")
                                
                            ts_micro = int(data['ts']) * 1000
                            
                            if 'asks' in data:
                                for ask in data['asks'][:depth_limit]:
                                    events.append((DEPTH_SELL_MASK, ts_micro, float(ask[0]), float(ask[1])))
                            if 'bids' in data:
                                for bid in data['bids'][:depth_limit]:
                                    events.append((DEPTH_BUY_MASK, ts_micro, float(bid[0]), float(bid[1])))
                                    
                        except orjson.JSONDecodeError as e:
                            error_count += 1
                            logging.error(f"[{targz_path} 行 {line_num}] JSON解析失败: {e}. 截断: {line[:100]}...")
                        except KeyError as e:
                            error_count += 1
                            logging.error(f"[{targz_path} 行 {line_num}] 缺失关键字段: {e}. 截断: {line[:100]}...")
                        except (ValueError, TypeError) as e:
                            error_count += 1
                            logging.error(f"[{targz_path} 行 {line_num}] 数据格式异常: {e}. 截断: {line[:100]}...")
                        except Exception as e:
                            error_count += 1
                            logging.critical(f"[{targz_path} 行 {line_num}] 未知严重错误: {e}. 截断: {line[:100]}...")
                        
                        # 熔断触发
                        if error_count > max_errors:
                            raise RuntimeError(f"中止！{targz_path} 错误次数超限 ({max_errors})，数据已受损。")
                            
    return np.array(events, dtype=STRUCT_DTYPE) if events else np.array([], dtype=STRUCT_DTYPE)

# 2. 解析 Trades -> 生成结构化数组 (包含 8h 修正)
def parse_trades_to_struct(zip_path):
    """解析 Trades CSV，修正时差，返回结构化数组"""
    if not os.path.exists(zip_path):
        return np.array([], dtype=STRUCT_DTYPE)
        
    events = []
    OFFSET_8H_MS = 28_800_000 
    
    with zipfile.ZipFile(zip_path, 'r') as z:
        csv_files = [f for f in z.namelist() if f.endswith('.csv')]
        if not csv_files: return np.array([], dtype=STRUCT_DTYPE)
        
        with z.open(csv_files[0]) as f:
            chunk_iter = pd.read_csv(f, chunksize=1_000_000)
            for chunk in chunk_iter:
                raw_ms = pd.to_numeric(chunk['created_time'], errors='coerce').astype(np.int64)
                ts_micro = (raw_ms + OFFSET_8H_MS) * 1000
                
                ev_mask = np.where(chunk['side'].str.lower() == 'buy', TRADE_BUY_MASK, TRADE_SELL_MASK)
                
                chunk_struct = np.empty(len(chunk), dtype=STRUCT_DTYPE)
                chunk_struct['ev'] = ev_mask.astype(np.uint64)
                chunk_struct['ts'] = ts_micro.astype(np.int64)
                chunk_struct['px'] = chunk['price'].astype(np.float64)
                chunk_struct['qty'] = chunk['size'].astype(np.float64)
                
                events.append(chunk_struct)
                
    return np.concatenate(events) if events else np.array([], dtype=STRUCT_DTYPE)

# 3. 单日合并与生成二进制文件 (.bin)
def process_single_day(date_str, ob_path, trades_path, output_dir):
    out_bin = os.path.join(output_dir, f"market_data_{date_str.replace('-', '_')}.bin")
    if os.path.exists(out_bin):
        return f"[{date_str}] BIN 已存在，跳过"
        
    ob_arr = parse_ob_to_struct(ob_path)
    tr_arr = parse_trades_to_struct(trades_path)
    
    if ob_arr.size == 0 or tr_arr.size == 0:
        return f" [{date_str}] 某一方数据缺失"
        
    combined = np.concatenate((ob_arr, tr_arr))
    combined = np.sort(combined, order='ts', kind='mergesort')
    
    with open(out_bin, "wb") as f:
        f.write(combined.tobytes())
        
    return f" [{date_str}] 写入 C++ 二进制文件成功！Tick总数: {len(combined)}"

# 4. 多进程调度
if __name__ == "__main__":
    
    OB_DIR = r"C:\Users\mrp\Desktop\okx ob btc 2026-01\okx ob btc 2026-01"
    TR_DIR = r"C:\Users\mrp\Desktop\okx trades btc 2026-01\okx trades btc 2026-01"
    BIN_OUT_DIR = r"C:\Users\mrp\Desktop\cpp_market_data"
    
    os.makedirs(BIN_OUT_DIR, exist_ok=True)
    
    start_date = datetime(2026, 1, 1)
    end_date = datetime(2026, 1, 31)
    
    tasks = []
    curr = start_date
    while curr <= end_date:
        d_str = curr.strftime("%Y-%m-%d")
        ob_p = os.path.join(OB_DIR, f"BTC-USDT-SWAP-L2orderbook-400lv-{d_str}.tar.gz")
        tr_p = os.path.join(TR_DIR, f"BTC-USDT-SWAP-trades-{d_str}.zip")
        tasks.append((d_str, ob_p, tr_p, BIN_OUT_DIR))
        curr += timedelta(days=1)
        
    print(f" 准备生成 {len(tasks)} 个 C++ 专属二进制文件...")
    
    with ProcessPoolExecutor(max_workers=1) as executor:
        futures = {executor.submit(process_single_day, *t): t for t in tasks}
        for f in as_completed(futures):
            print(f.result())
            
    print("\n 数据清洗完成")