# Log Analyzer – 两遍处理与规则演进系统

本工程实现“第一遍规则演进 + 第二遍统计聚合 + 第三程序描述审批台”。
包含索引双缓冲、缓冲队列与多智能体委员会、历史日志检索对抗验证、以及可配置阈值与早停。

## 快速开始
```bash
python -m store.dao --init --db ./data/log_analyzer.sqlite3

python bin/p0_bootstrap_seed_templates --paths sample_logs/example1.gz

python -m store.dao --init --db ./data/log_analyzer.sqlite3 --ensure-dir




python -m bin.p1_run_first_pass \
  --path test.gz \
  --size-threshold 15 \
  --micro-batch 100 \
  --max-per-micro-batch 100 \
  --await-llm \
  --force-flush
python bin/p1_run_first_pass --path sample_logs/example1.gz
python bin/p2_run_second_pass --path sample_logs/example1.gz --file-id auto
# 可选：审批台
streamlit run bin/p3_launch_description_ui.py
```
