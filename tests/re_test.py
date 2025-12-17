

import sqlite3
import re

DB_PATH = 'data/log_analyzer.sqlite3'

def smart_regex_transform_v3(nomal_pattern):
    """
    针对 NUMNUM = [0-9.-]+ 的专用优化转换函数
    """
    
    # -------------------------------------------------------------
    # 修改点在这里：
    # 在 replacement 字符串中，必须使用双反斜杠 \\d
    # 这样 re.sub 处理后，生成的字符串才会是单反斜杠的 [\d.-]+
    # -------------------------------------------------------------
    target_regex = r"[\\d.-]+"
    
    # 核心替换逻辑
    # 即使输入是 NUMNUMNUMNUM，也会被合并替换为一个 [\d.-]+
    clean_pattern = re.sub(r'(NUMNUM)+', target_regex, nomal_pattern)
    
    return clean_pattern

def batch_update_patterns_final():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n>>> 开始批量更新 Pattern (V3 - 修复转义版)...")

    # 1. 读取数据
    cursor.execute("SELECT template_id, pattern_nomal FROM regex_template")
    rows = cursor.fetchall()
    
    updates = []
    
    for row in rows:
        t_id = row[0]
        p_nomal = row[1]
        
        # 2. 执行转换
        p_converted = smart_regex_transform_v3(p_nomal)
        
        updates.append((p_converted, t_id))
        
        # 打印调试 (前3条)
        if t_id <= 3:
            print(f"ID {t_id}:")
            print(f"  [原] {p_nomal}")
            print(f"  [新] {p_converted}")
            print("-" * 60)

    # 3. 提交数据库
    cursor.executemany("UPDATE regex_template SET pattern = ?, updated_at = datetime('now') WHERE template_id = ?", updates)
    conn.commit()
    print(f">>> 成功更新 {cursor.rowcount} 条记录。")
    conn.close()

def verify_complex_formats():
    print("\n>>> 正在验证复杂 NUMNUM 格式匹配...")
    
    # 手动构造一个验证用的正则对象
    # 注意：这里是在写 pattern (匹配模式)，所以用单反斜杠 [\d.-]+ 是合法的
    # 我们要验证的是上面函数生成出来的结果字符串是否有效
    
    # 模拟上面函数转换后的结果字符串
    generated_regex_str = r"^Values: [\d.-]+, [\d.-]+, [\d.-]+, [\d.-]+, [\d.-]+$"
    
    try:
        pattern = re.compile(generated_regex_str)
        print(f"✅ [正则编译成功] {generated_regex_str}")
    except re.error as e:
        print(f"❌ [正则编译失败] {e}")
        return

    test_log = "Values: 111, 001, 010-1, -12, 010-0-1-.912"
    
    if pattern.match(test_log):
        print(f"✅ [匹配通过] {test_log}")
    else:
        print(f"❌ [匹配失败] {test_log}")

if __name__ == "__main__":
    verify_complex_formats()
    batch_update_patterns_final()