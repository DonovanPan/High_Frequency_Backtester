import os

def peek_large_file(file_path, num_bytes=200):
    print(f"正在探测文件: {file_path}")
    print(f"文件总大小: {os.path.getsize(file_path) / (1024**3):.2f} GB\n")
    
    with open(file_path, 'rb') as f:
        raw_head = f.read(num_bytes)
        
    print("【1. 原始二进制字节形态】:")
    print(raw_head)
    print("\n" + "-"*40 + "\n")
    
    print("【2. 尝试作为文本强制解码】:")
    try:
        # 尝试用人类可读的 utf-8 格式解码
        text_head = raw_head.decode('utf-8')
        print(text_head)
    except UnicodeDecodeError:
        print(" 文件里面包含了无法转换为字符的二进制乱码。")

# --- 运行测试 ---
your_file_path = r"C:\Users\mrp\Desktop\BTC-USDT-SWAP-L2orderbook-400lv-2026-01-01.data"
peek_large_file(your_file_path)