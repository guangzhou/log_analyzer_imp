import re

# 原始输入
text = "Link  2-0 , 次要道路, 快速后匝道,   主路, 普通, 右前方,   77[m], , Gps:8, max_k:0.0228, angle:112.2677, s:(1468~1545)."

print("0️⃣ 原始文本:")
print(repr(text))
print()

# 检查是否有预处理：删除 '-' ?
# ❌ 如果你有这行，就是罪魁祸首！
# text = text.replace('-', '')
# print("⚠️ 预处理后（删-）:", repr(text))

# 使用统一正则，一次性替换
pattern = r'(?<![a-zA-Z0-9])-?(?:\d+(?:\.\d*)?|\.\d+)'
result = re.sub(pattern, '_num_', text)

print("✅ 最终结果:")
print(repr(result)) 
print("📄 可读对比:")
print("原始:", text)
print("结果:", result)
print("_num_-_num_") 