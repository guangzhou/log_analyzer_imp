# 最小侵入式补丁说明

本补丁仅新增与改动以下文件：
- core/keytext.py  新增
- bin/p1_run_first_pass.py  覆盖

变更点：
1) 在第一遍 P1 中，生成 `xx.normal.txt` 后，新增产出：
   - `xx_uniq.txt`：关键文本排序去重
   - `xx_uniq_with_count.tsv`：关键文本 + 在 normal 中出现的次数
2) 第一遍的匹配与缓冲改为基于 `xx_uniq.txt` 的关键文本，减少重复匹配。
3) 其余 LLM 阈值触发、模板写入、索引双缓冲与原子切换逻辑保持不变。

使用：
将本补丁解压覆盖至工程根目录，然后运行：
python -m bin.p1_run_first_pass --path your.gz --await-llm --force-flush
