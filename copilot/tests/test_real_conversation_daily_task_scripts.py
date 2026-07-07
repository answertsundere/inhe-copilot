import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_help(script: str):
    return subprocess.run(
        [sys.executable, script, "--help"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_real_conversation_import_script_help_runs_without_pythonpath():
    result = _run_help("scripts/import_real_conversation_eval_cases.py")

    assert result.returncode == 0
    assert "--source-dir" in result.stdout
    assert "--min-turns" in result.stdout


def test_daily_replay_script_help_runs_without_pythonpath():
    result = _run_help("scripts/run_daily_real_conversation_replay.py")

    assert result.returncode == 0
    assert "--source-dir" in result.stdout
    assert "--generate-repair-tasks" in result.stdout
    assert "--turn-timeout-seconds" in result.stdout
    assert "--progress-log" in result.stdout


def test_daily_replay_wrapper_has_dynamic_date_and_apply_flow():
    content = (PROJECT_ROOT / "scripts/run_daily_real_conversation_replay_task.ps1").read_text(encoding="utf-8")

    assert "run_daily_real_conversation_replay.py" in content
    assert "--apply" in content
    assert "--generate-repair-tasks" in content
    assert "--json-output" in content
    assert "Start-Process" in content
    assert "RedirectStandardOutput" in content
    assert "RedirectStandardError" in content
    assert 'Get-Date -Format "yy-M-d"' in content
    assert 'Get-Date -Format "yyyyMMdd"' in content
    assert "26-6-25" not in content
    assert "20260625" not in content


def test_daily_replay_setup_script_registers_task_without_running_replay():
    content = (PROJECT_ROOT / "scripts/setup_daily_real_conversation_replay_task.ps1").read_text(encoding="utf-8")

    assert "Register-ScheduledTask" in content
    assert "INHE Copilot Daily Real Conversation Replay" in content
    assert "ProjectDir" in content
    assert "SourceDir" in content
    assert "Time" in content
    assert '[string]$Time = "13:00"' in content
    assert "SampleLimit" in content
    assert "MinTurns" in content
    assert "WhatIfMode" in content
    assert "WorkingDirectory" in content
    assert "schtasks /Run" in content
    assert "--apply" not in content
    assert "run_daily_real_conversation_replay.py" not in content
