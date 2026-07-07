import numpy as np

file_path = r"C:\Users\mrp\Desktop\obnpz\2026_01_01.npz"

with np.load(file_path, mmap_mode='r') as data:
    keys = data.files
    #print(keys) 
    first_several_rows = data['data'][:5]

    print(first_several_rows)