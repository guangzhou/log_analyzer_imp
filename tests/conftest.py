
# -*- coding: utf-8 -*-
"""
PyTest 全局夹具：
- 临时数据库初始化（基于 schema.sql）
- 统一设置环境变量 LOG_ANALYZER_DB 指向临时 sqlite 文件
- 提供样本数据与对抗样本
"""
import os, sqlite3, shutil, tempfile, pathlib, sys
import pytest

# 让 tests 可从项目根部导入 core / store 模块
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from store import dao

@pytest.fixture(scope="session", autouse=True)
def _setup_tmp_db():
    tmpdir = tempfile.mkdtemp(prefix="log_analyzer_test_")
    db_path = os.path.join(tmpdir, "test.sqlite3")
    os.environ["LOG_ANALYZER_DB"] = db_path
    # 初始化数据库
    dao.init_db(db_path=db_path)
    yield db_path
    shutil.rmtree(tmpdir, ignore_errors=True)

@pytest.fixture
def cluster_samples_vx():
    return [
        "Auto gen vx graph(DAADBevDetTemporal6v) failed",
        "Auto gen vx graph(DAADBevDetTemporal5v) failed",
        "Auto gen vx graph(DAADBevDetTemporal3v) failed"
    ]

@pytest.fixture
def adversary_negatives():
    return [
        "[ FusionMap ] laneloc is invalid ...",
        "system started ok",
        "upload success"
    ]
