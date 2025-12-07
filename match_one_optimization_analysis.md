# match_one 函数优化分析

## 🔍 当前实现分析

```python
def match_one(self, text: str) -> Optional[int]:
    for tid, pat, creg in self.items:
        if creg.search(text):
            return tid
    return None
```

### 当前算法特点
- **时间复杂度**：O(n×m)，其中 n 是模板数量，m 是文本长度
- **空间复杂度**：O(1)
- **匹配策略**：线性搜索，找到第一个匹配就返回
- **优点**：简单直接，内存占用小
- **缺点**：随着模板数量增加，性能线性下降

## 🚀 优化方案

### 方案1：Aho-Corasick 自动机（推荐）

**适用场景**：大量固定字符串匹配

```python
import ahocorasick

class OptimizedCompiledIndex:
    def __init__(self, items: List[dict], nomal=True):
        self.items = []
        self.automaton = ahocorasick.Automaton()
        
        pattern_key = "pattern_nomal" if nomal else "pattern"
        for it in items:
            if it.get(pattern_key):
                try:
                    # 对于简单字符串模式，使用 Aho-Corasick
                    pattern = it[pattern_key]
                    if self._is_simple_pattern(pattern):
                        self.automaton.add_word(pattern, it["template_id"])
                    else:
                        # 复杂正则仍使用原方法
                        compiled_pattern = re.compile(pattern)
                        self.items.append((it["template_id"], pattern_key, compiled_pattern))
                except re.error as e:
                    template_id = it.get('template_id')
                    logger.error(f"Failed to compile pattern '{pattern}' for template_id {template_id}: {e}")
                    if template_id is not None:
                        deactivate_template(template_id)
        
        self.automaton.make_automaton()
    
    def _is_simple_pattern(self, pattern: str) -> bool:
        """判断是否为简单字符串模式（无正则特殊字符）"""
        special_chars = r'\.*+?^$[]{}()|\\'
        return not any(char in pattern for char in special_chars)
    
    def match_one(self, text: str) -> Optional[int]:
        # 先用 Aho-Corasick 快速匹配简单字符串
        for end_idx, template_id in self.automaton.iter(text):
            return template_id
        
        # 再用正则匹配复杂模式
        for tid, pat, creg in self.items:
            if creg.search(text):
                return tid
        return None
```

**性能提升**：
- 构建时间：O(总模式长度)
- 匹配时间：O(文本长度 + 匹配数量)
- 适合：大量固定字符串，少量复杂正则

### 方案2：模式分层匹配

**适用场景**：可以按匹配概率或复杂度分层

```python
class LayeredCompiledIndex:
    def __init__(self, items: List[dict], nomal=True):
        self.fast_patterns = []  # 简单高频模式
        self.normal_patterns = []  # 普通模式
        self.complex_patterns = []  # 复杂低频模式
        
        pattern_key = "pattern_nomal" if nomal else "pattern"
        for it in items:
            if it.get(pattern_key):
                try:
                    compiled_pattern = re.compile(it[pattern_key])
                    complexity = self._calculate_complexity(it[pattern_key])
                    
                    item_data = (it["template_id"], pattern_key, compiled_pattern)
                    
                    if complexity < 3:
                        self.fast_patterns.append(item_data)
                    elif complexity < 7:
                        self.normal_patterns.append(item_data)
                    else:
                        self.complex_patterns.append(item_data)
                        
                except re.error as e:
                    # 错误处理...
                    pass
    
    def _calculate_complexity(self, pattern: str) -> int:
        """计算正则表达式复杂度"""
        complexity = 0
        # 简单的复杂度计算
        if '*' in pattern or '+' in pattern:
            complexity += 2
        if '?' in pattern:
            complexity += 1
        if '|' in pattern:
            complexity += 3
        if '[' in pattern or ']' in pattern:
            complexity += 2
        if '(' in pattern:
            complexity += 3
        return complexity
    
    def match_one(self, text: str) -> Optional[int]:
        # 按层级匹配，先简单后复杂
        for patterns in [self.fast_patterns, self.normal_patterns, self.complex_patterns]:
            for tid, pat, creg in patterns:
                if creg.search(text):
                    return tid
        return None
```

### 方案3：缓存优化

**适用场景**：有重复文本的批处理

```python
from functools import lru_cache
import hashlib

class CachedCompiledIndex:
    def __init__(self, items: List[dict], nomal=True, cache_size=10000):
        self.items = []
        pattern_key = "pattern_nomal" if nomal else "pattern"
        
        for it in items:
            if it.get(pattern_key):
                try:
                    compiled_pattern = re.compile(it[pattern_key])
                    self.items.append((it["template_id"], pattern_key, compiled_pattern))
                except re.error as e:
                    # 错误处理...
                    pass
        
        # 缓存最近的结果
        self._match_one_cached = lru_cache(maxsize=cache_size)(self._match_one_uncached)
    
    def _match_one_uncached(self, text: str) -> Optional[int]:
        for tid, pat, creg in self.items:
            if creg.search(text):
                return tid
        return None
    
    def match_one(self, text: str) -> Optional[int]:
        return self._match_one_cached(text)
    
    def clear_cache(self):
        """清空缓存"""
        self._match_one_cached.cache_clear()
```

### 方案4：并行匹配（适合大量模式）

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import math

class ParallelCompiledIndex:
    def __init__(self, items: List[dict], nomal=True, chunk_size=100):
        self.items = []
        self.chunk_size = chunk_size
        
        pattern_key = "pattern_nomal" if nomal else "pattern"
        for it in items:
            if it.get(pattern_key):
                try:
                    compiled_pattern = re.compile(it[pattern_key])
                    self.items.append((it["template_id"], pattern_key, compiled_pattern))
                except re.error as e:
                    # 错误处理...
                    pass
    
    def _match_chunk(self, chunk: List, text: str) -> Optional[int]:
        """匹配一个块的模式"""
        for tid, pat, creg in chunk:
            if creg.search(text):
                return tid
        return None
    
    def match_one(self, text: str, max_workers: int = 4) -> Optional[int]:
        if len(self.items) <= self.chunk_size:
            # 少量模式直接串行匹配
            return self._match_chunk(self.items, text)
        
        # 将模式分块并行匹配
        chunks = [
            self.items[i:i + self.chunk_size]
            for i in range(0, len(self.items), self.chunk_size)
        ]
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self._match_chunk, chunk, text)
                for chunk in chunks
            ]
            
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    return result
        
        return None
```

### 方案5：预编译优化（推荐组合）

```python
class HighlyOptimizedCompiledIndex:
    def __init__(self, items: List[dict], nomal=True):
        self.string_patterns = {}  # 纯字符串匹配
        self.regex_patterns = []   # 正则表达式匹配
        self.complex_regex = []    # 复杂正则（最后匹配）
        
        pattern_key = "pattern_nomal" if nomal else "pattern"
        
        for it in items:
            if it.get(pattern_key):
                pattern = it[pattern_key]
                try:
                    if self._is_literal_string(pattern):
                        # 纯字符串，用字典快速查找
                        self.string_patterns[pattern] = it["template_id"]
                    else:
                        compiled_pattern = re.compile(pattern)
                        complexity = self._get_complexity(pattern)
                        
                        item_data = (it["template_id"], pattern_key, compiled_pattern)
                        
                        if complexity < 5:
                            self.regex_patterns.append(item_data)
                        else:
                            self.complex_regex.append(item_data)
                            
                except re.error as e:
                    # 错误处理...
                    pass
        
        # 按使用频率排序（如果有统计数据）
        self.regex_patterns.sort(key=lambda x: getattr(x[2], 'match_count', 0), reverse=True)
    
    def _is_literal_string(self, pattern: str) -> bool:
        """判断是否为纯字符串"""
        try:
            re.compile(pattern)
            # 如果编译后的模式与原字符串相同，说明是纯字符串
            return re.escape(pattern) == pattern
        except:
            return False
    
    def _get_complexity(self, pattern: str) -> int:
        """获取正则复杂度"""
        # 简化的复杂度评估
        score = 0
        score += pattern.count('*') * 2
        score += pattern.count('+') * 2
        score += pattern.count('?') * 1
        score += pattern.count('|') * 3
        score += pattern.count('(') * 2
        score += pattern.count('[') * 2
        return score
    
    def match_one(self, text: str) -> Optional[int]:
        # 1. 最快：纯字符串匹配
        if text in self.string_patterns:
            return self.string_patterns[text]
        
        # 2. 较快：简单正则匹配
        for tid, pat, creg in self.regex_patterns:
            if creg.search(text):
                # 更新使用统计
                creg.match_count = getattr(creg, 'match_count', 0) + 1
                return tid
        
        # 3. 最后：复杂正则匹配
        for tid, pat, creg in self.complex_regex:
            if creg.search(text):
                creg.match_count = getattr(creg, 'match_count', 0) + 1
                return tid
        
        return None
```

## 📊 性能对比表

| 方案 | 适用场景 | 构建时间 | 匹配时间 | 内存占用 | 实现复杂度 |
|------|----------|----------|----------|----------|------------|
| 原始 | 少量模式 | O(n) | O(n×m) | 低 | 简单 |
| Aho-Corasick | 大量固定字符串 | O(总长度) | O(m) | 中 | 中等 |
| 分层匹配 | 可分层的模式 | O(n) | O(k×m) | 低 | 中等 |
| 缓存优化 | 重复文本 | O(n) | O(n×m) 首次 | 中+缓存 | 简单 |
| 并行匹配 | 大量模式 | O(n) | O(n×m/worker) | 低×worker | 中等 |
| 预编译优化 | 混合场景 | O(n) | O(k×m) | 中 | 复杂 |

## 🎯 推荐方案

### 场景1：模板数量 < 100
**推荐**：保持原始实现，添加缓存即可

### 场景2：模板数量 100-1000，包含大量固定字符串
**推荐**：Aho-Corasick + 正则组合

### 场景3：模板数量 > 1000，混合模式
**推荐**：预编译优化方案（方案5）

### 场景4：批处理，有重复文本
**推荐**：任何方案 + 缓存优化

## 💡 实施建议

1. **先做性能分析**：了解实际的模板数量和类型分布
2. **渐进式优化**：先实施简单的缓存，再考虑复杂方案
3. **性能测试**：用实际数据测试各种方案的效果
4. **监控指标**：添加匹配时间、命中率等监控

选择优化方案时，要考虑你的具体使用场景和数据特征！
