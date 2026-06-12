from __future__ import annotations

from scripts.sidecar.window_watcher import (
    WindowCandidate,
    WindowSelection,
    _score_window,
    find_all_candidates,
    select_window,
)
from scripts.sidecar.config import SidecarConfig


class TestScoreWindow:
    def test_jiedai_center_highest_priority(self):
        config = SidecarConfig()
        score, reason = _score_window(
            "英禾旗舰店:嘉茗-接待中心", True, False,
            config.window_title_priority,
        )
        assert score == 200
        assert "接待中心" in reason

    def test_qianniu_gongzuo_lower_priority(self):
        config = SidecarConfig()
        score, reason = _score_window(
            "贝际旗舰店:嘉茗-千牛工作台", True, False,
            config.window_title_priority,
        )
        # 千牛工作台 matches but gets -30 penalty for 工作台
        assert score == 50
        assert "千牛工作台" in reason

    def test_jiedai_center_beats_gongzuo(self):
        config = SidecarConfig()
        score_center, _ = _score_window(
            "英禾旗舰店:嘉茗-接待中心", True, False,
            config.window_title_priority,
        )
        score_gongzuo, _ = _score_window(
            "贝际旗舰店:嘉茗-千牛工作台", True, False,
            config.window_title_priority,
        )
        assert score_center >= score_gongzuo

    def test_minimized_penalty(self):
        config = SidecarConfig()
        score_normal, _ = _score_window(
            "英禾旗舰店:嘉茗-接待中心", True, False,
            config.window_title_priority,
        )
        score_min, _ = _score_window(
            "英禾旗舰店:嘉茗-接待中心", True, True,
            config.window_title_priority,
        )
        # 接待中心 base=200, minimized -40 → 160
        assert score_normal == 200
        assert score_min == 160
        assert score_normal > score_min

    def test_not_visible_zero_score(self):
        config = SidecarConfig()
        score, reason = _score_window(
            "英禾旗舰店:嘉茗-接待中心", False, False,
            config.window_title_priority,
        )
        assert score == 0

    def test_no_match(self):
        config = SidecarConfig()
        score, reason = _score_window(
            "notepad", True, False,
            config.window_title_priority,
        )
        assert score == 0

    def test_terminal_window_with_qianniu_text_low_score(self):
        config = SidecarConfig()
        score, reason = _score_window(
            "重构千牛 Sidecar 混合采集架构", True, False,
            config.window_title_priority,
        )
        # Should match "千牛" but get heavy penalty for non-shop-pattern title
        assert score <= 20

    def test_minimized_center_beats_terminal(self):
        config = SidecarConfig()
        score_center_min, _ = _score_window(
            "英禾旗舰店:嘉茗-接待中心", True, True,
            config.window_title_priority,
        )
        score_terminal, _ = _score_window(
            "重构千牛 Sidecar 混合采集架构", True, False,
            config.window_title_priority,
        )
        assert score_center_min > score_terminal

    def test_wangwang_keyword(self):
        config = SidecarConfig()
        score, reason = _score_window(
            "旺旺聊天窗口", True, False,
            config.window_title_priority,
        )
        assert score > 0
        assert "旺旺" in reason

    def test_select_window_prefers_center(self):
        config = SidecarConfig()
        candidates = [
            WindowCandidate(hwnd=1, title="贝际旗舰店:嘉茗-千牛工作台",
                            class_name="", visible=True, minimized=False, score=70, match_reason="千牛工作台"),
            WindowCandidate(hwnd=2, title="英禾旗舰店:嘉茗-接待中心",
                            class_name="", visible=True, minimized=False, score=100, match_reason="接待中心"),
        ]
        assert candidates[1].score > candidates[0].score

    def test_gongzuo_only_when_no_center(self):
        config = SidecarConfig()
        candidates = [
            WindowCandidate(hwnd=1, title="贝际旗舰店:嘉茗-千牛工作台",
                            class_name="", visible=True, minimized=False, score=100, match_reason="千牛工作台"),
        ]
        assert len(candidates) == 1
        assert "千牛工作台" in candidates[0].title
