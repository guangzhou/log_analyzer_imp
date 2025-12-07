#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试模板删除功能的脚本
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from store.dao import init_db, write_templates, fetch_all_templates, deactivate_template
from core.matcher import CompiledIndex

def test_template_deletion():
    """测试当正则表达式编译失败时删除模板的功能"""
    
    # 初始化测试数据库
    test_db = "./data/test_template_deletion.sqlite3"
    if os.path.exists(test_db):
        os.remove(test_db)
    
    print("1. 初始化测试数据库...")
    init_db(db_path=test_db)
    
    # 创建测试模板数据
    print("2. 创建测试模板...")
    test_templates = [
        {
            "pattern_nomal": r"valid pattern \d+",
            "sample_log": "valid pattern 123",
            "source": "test"
        },
        {
            "pattern_nomal": r"invalid pattern [unclosed bracket",  # 无效的正则表达式
            "sample_log": "invalid pattern test",
            "source": "test"
        },
        {
            "pattern_nomal": r"another valid pattern \w+",
            "sample_log": "another valid pattern abc",
            "source": "test"
        }
    ]
    
    template_ids = write_templates(test_templates)
    print(f"创建了 {len(template_ids)} 个模板，IDs: {template_ids}")
    
    # 验证模板已创建
    print("3. 验证模板创建状态...")
    active_templates = fetch_all_templates(active_only=True)
    print(f"活跃模板数量: {len(active_templates)}")
    for template in active_templates:
        print(f"  - template_id: {template['template_id']}, pattern: {template['pattern_nomal']}")
    
    # 模拟 CompiledIndex 初始化，这应该会触发无效模板的删除
    print("4. 测试 CompiledIndex 初始化（应该删除无效模板）...")
    
    # 设置环境变量使用测试数据库
    os.environ["LOG_ANALYZER_DB"] = test_db
    
    try:
        # 获取所有模板（包括无效的）
        all_templates = []
        for template in fetch_all_templates(active_only=False):
            all_templates.append(dict(template))
        
        print(f"总模板数量: {len(all_templates)}")
        
        # 创建 CompiledIndex，这应该会编译失败的模板并删除它们
        index = CompiledIndex(all_templates, nomal=True)
        
        print(f"CompiledIndex 成功编译了 {len(index.items)} 个模板")
        
    except Exception as e:
        print(f"CompiledIndex 初始化出错: {e}")
    
    # 验证无效模板是否已被删除
    print("5. 验证删除结果...")
    active_templates_after = fetch_all_templates(active_only=True)
    print(f"删除后活跃模板数量: {len(active_templates_after)}")
    for template in active_templates_after:
        print(f"  - template_id: {template['template_id']}, pattern: {template['pattern_nomal']}")
    
    # 清理测试数据库
    if os.path.exists(test_db):
        os.remove(test_db)
        print("6. 清理测试数据库完成")
    
    print("\n测试完成！")

if __name__ == "__main__":
    test_template_deletion()
