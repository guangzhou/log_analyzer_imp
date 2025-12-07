import sqlite3
import pandas as pd
from tqdm import tqdm

# 连接到数据库
conn = sqlite3.connect('data/log_analyzer.sqlite3')
cursor = conn.cursor()

# 读取 CSV 文件
try:
    df = pd.read_csv('12.csv', encoding='utf-8')
except Exception as e:
    print(f"读取CSV文件时出错: {e}")
    # 尝试其他编码
    df = pd.read_csv('12.csv', encoding='latin-1')

print(f"成功读取 {len(df)} 行，{len(df.columns)} 列")

# 逐行插入，处理错误
success_count = 0
fail_count = 0

for index, row in tqdm(df.iterrows(), total=len(df)):
    try:
        # 确保行数据有足够的列（11列）
        values = list(row)
        if len(values) < 11:
            # 用 None 填充缺失的列
            values.extend([None] * (11 - len(values)))
        
        # 执行插入
        cursor.execute('''
            INSERT INTO regex_template 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', values)
        success_count += 1
    except Exception as e:
        print(f"第 {index + 1} 行插入失败: {e}")
        print(f"失败的数据: {values}")
        fail_count += 1
        conn.rollback()  # 回滚当前事务
        continue

conn.commit()
print(f"导入完成: 成功 {success_count} 行, 失败 {fail_count} 行")
conn.close()