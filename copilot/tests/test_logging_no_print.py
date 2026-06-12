"""
日志规范测试 - 验证 app/ 目录下无 print() 调用残留
"""

import sys
import os
import ast

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _collect_python_files(app_dir):
    """递归收集 app/ 目录下所有 .py 文件"""
    py_files = []
    for root, dirs, files in os.walk(app_dir):
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))
    return py_files


def _has_print_call(filepath):
    """用 AST 分析文件是否包含 print() 调用（排除字符串内的 print）"""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        source = f.read()

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        # 无法解析的文件跳过
        return False

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # 检测直接调用: print(...)
            if isinstance(func, ast.Name) and func.id == "print":
                violations.append((filepath, node.lineno))

    return violations


class TestNoPrintStatements:
    """app/ 目录下不应残留 print() 语句"""

    def test_no_print_in_app_directory(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        app_dir = os.path.join(base_dir, "app")
        assert os.path.isdir(app_dir), f"app/ directory not found at {app_dir}"

        py_files = _collect_python_files(app_dir)
        assert len(py_files) > 0, "No .py files found in app/"

        all_violations = []
        for filepath in py_files:
            violations = _has_print_call(filepath)
            all_violations.extend(violations)

        assert len(all_violations) == 0, (
            f"Found print() calls in app/ directory:\n"
            + "\n".join(f"  {fp}:{line}" for fp, line in all_violations)
        )
