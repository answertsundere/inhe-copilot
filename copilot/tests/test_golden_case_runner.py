"""
test_golden_case_runner — Phase 1D Golden Case Runner 测试
"""

import json
import os
import pytest
import tempfile
import shutil


class TestGoldenCaseRunner:
    def test_load_empty_dir(self):
        tmpdir = tempfile.mkdtemp()
        try:
            from tests.golden_case_runner import load_golden_cases
            # Override dir temporarily
            import tests.golden_case_runner as gcr
            orig = gcr.GOLDEN_CASES_DIR
            gcr.GOLDEN_CASES_DIR = tmpdir
            cases = load_golden_cases()
            gcr.GOLDEN_CASES_DIR = orig
            assert cases == []
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_load_with_cases(self):
        tmpdir = tempfile.mkdtemp()
        try:
            case = {
                "case_id": "BC-TEST",
                "name": "Test case",
                "input": {"customer_message": "你好"},
                "expect": {"allowed_intents": ["general"]},
            }
            fpath = os.path.join(tmpdir, "BC-TEST.json")
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(case, f, ensure_ascii=False)

            from tests.golden_case_runner import load_golden_cases
            import tests.golden_case_runner as gcr
            orig = gcr.GOLDEN_CASES_DIR
            gcr.GOLDEN_CASES_DIR = tmpdir
            cases = load_golden_cases()
            gcr.GOLDEN_CASES_DIR = orig
            assert len(cases) == 1
            assert cases[0]["case_id"] == "BC-TEST"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ignores_non_json(self):
        tmpdir = tempfile.mkdtemp()
        try:
            fpath = os.path.join(tmpdir, "readme.txt")
            with open(fpath, "w") as f:
                f.write("not json")
            from tests.golden_case_runner import load_golden_cases
            import tests.golden_case_runner as gcr
            orig = gcr.GOLDEN_CASES_DIR
            gcr.GOLDEN_CASES_DIR = tmpdir
            cases = load_golden_cases()
            gcr.GOLDEN_CASES_DIR = orig
            assert cases == []
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
