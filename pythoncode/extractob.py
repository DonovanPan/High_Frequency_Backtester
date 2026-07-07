import os
import tarfile
import orjson 
import numpy as np
import gc
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed 

# V2 事件掩码与全局结构体定义
DEPTH_EVENT      = 1 << 28 
BUY_SIDE         = 1
SELL_SIDE        = 2
DEPTH_BUY_MASK   = DEPTH_EVENT | BUY_SIDE
DEPTH_SELL_MASK  = DEPTH_EVENT | SELL_SIDE

STRUCT_DTYPE = np.dtype([('ev', 'u8'), ('ts', 'i8'), ('px', 'f8'), ('qty', 'f8')])

# 1. 核心解析模块
def extract_ob_from_targz(targz_path, chunk_lines=20000, depth_limit=20):
    if not os.path.exists(targz_path):
        return np.array([], dtype=STRUCT_DTYPE)
    
    matrix_list = []
    current_chunk = []
    
    with tarfile.open(targz_path, 'r:gz') as tar:
        for member in tar.getmembers():
            if member.isfile():
                f = tar.extractfile(member)
                if f is not None:
                    for line_bytes in f:
                        line = line_bytes.strip()
                        if not line: continue
                            
                        current_chunk.append(line)
                        
                        if len(current_chunk) >= chunk_lines:
                            chunk_matrix = _parse_ob_chunk(current_chunk, depth_limit)
                            if chunk_matrix.size > 0:
                                matrix_list.append(chunk_matrix)
                            current_chunk = [] 
                            
                    if current_chunk:
                        chunk_matrix = _parse_ob_chunk(current_chunk, depth_limit)
                        if chunk_matrix.size > 0:
                            matrix_list.append(chunk_matrix)
                        current_chunk = []

    return np.concatenate(matrix_list) if matrix_list else np.array([], dtype=STRUCT_DTYPE)

def _parse_ob_chunk(json_bytes_list, depth_limit):
    """使用紧凑结构体解析字节流"""
    events = []
    for line_bytes in json_bytes_list:
        try:
            data = orjson.loads(line_bytes)
            if 'ts' not in data: continue
            
            ts_micro = int(data['ts']) * 1000 
            
            if 'asks' in data:
                for ask in data['asks'][:depth_limit]:
                    events.append((DEPTH_SELL_MASK, ts_micro, float(ask[0]), float(ask[1])))
                    
            if 'bids' in data:
                for bid in data['bids'][:depth_limit]:
                    events.append((DEPTH_BUY_MASK, ts_micro, float(bid[0]), float(bid[1])))
        except Exception:
            continue
            
    return np.array(events, dtype=STRUCT_DTYPE) if events else np.array([], dtype=STRUCT_DTYPE)


# 2. 单日独立任务模块
def process_single_day_task(date_str, ob_targz_path, output_dir):
    output_npz = os.path.join(output_dir, f"{date_str.replace('-', '_')}.npz")
    if os.path.exists(output_npz):
        return f"[{date_str}] 文件已存在，跳过"

    combined_events = extract_ob_from_targz(ob_targz_path, depth_limit=20)
    
    if combined_events.size == 0:
        return f"[{date_str}] 提取失败或无数据"

    # 按结构体字段 'ts' 进行排序
    combined_events = np.sort(combined_events, order='ts', kind='mergesort')
    
    np.savez_compressed(output_npz, data=combined_events)
    
    event_count = len(combined_events)
    del combined_events
    gc.collect()
    
    return f" [{date_str}] 处理完成！生成事件数: {event_count}"


# 3. 进程池调度主程序
if __name__ == "__main__":
    OB_INPUT_DIR = r"C:\Users\mrp\Desktop\okx ob btc 2026-01\okx ob btc 2026-01"
    OUTPUT_DIR = r"C:\Users\mrp\Desktop\obnpz" 
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    tasks = []
    start_date = datetime(2026, 1, 1)
    end_date = datetime(2026, 1, 31)
    
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        ob_targz_filename = f"BTC-USDT-SWAP-L2orderbook-400lv-{date_str}.tar.gz"
        ob_targz_path = os.path.join(OB_INPUT_DIR, ob_targz_filename)
        tasks.append((date_str, ob_targz_path, OUTPUT_DIR))
        current_date += timedelta(days=1)
        
    print(f" 共计生成了 {len(tasks)} 个单日清洗任务。")
    print(" 正在唤醒多核并发处理...\n")
    
    MAX_PROCESSES = 4
    with ProcessPoolExecutor(max_workers=MAX_PROCESSES) as executor:
        futures = {executor.submit(process_single_day_task, *task): task for task in tasks}
        for future in as_completed(futures):
            try:
                print(future.result())
            except Exception as exc:
                print(f" 任务发生严重错误: {exc}")

    print("\n 全月数据极速清洗完毕！")