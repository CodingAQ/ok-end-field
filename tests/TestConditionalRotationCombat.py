# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

import pyautogui

from src.tasks.onetime.AutoCombatLogic import AutoCombatLogic


class _FakeTask:
    """模拟 BaseEfTask，供 AutoCombatLogic.run() 在无游戏环境下测试。

    记录所有释放动作到 self.actions，供断言。
    """

    def __init__(self, battle_config, ults=(), link=False, skill=3):
        self._cfg = battle_config
        self._ults = {str(u) for u in ults}
        self._link = link
        self._skill = skill
        self._time = 0.0
        self._frame = 0
        self._exited = False
        self.actions = []
        self.debug = False
        # 模拟「技力随时间变化」：skill 可为 int（恒定）或 list（按帧索引，只读不消费）
        # 模拟「发键 no-op」：send_key_consumes=False 时发键不扣技力
        self.send_key_consumes = True
        self.link_fired_at_frame = None  # 连携技实际释放帧（供「立即性」断言）
        self.ult_fired_at_frame = None   # 终结技实际释放帧

    # ── 时间 / 帧 ──
    def active_time(self):
        return self._time

    def sleep(self, t):
        self._time += t

    def next_frame(self):
        self._time += 0.1
        self._frame += 1

    # ── 战斗状态 ──
    def in_combat(self, required_yellow=0):
        return not self._exited

    def in_team(self):
        return True

    def ocr_lv(self):
        return False

    def _check_single_exit_condition(self):
        return self._frame > 30

    def is_combat_ended(self):
        if self._frame > 30:
            self._exited = True
            return True
        return False

    def in_bg(self):
        return False

    # ── 交互（no-op）──
    def screenshot(self, *a, **k):
        pass

    def active_and_send_mouse_delta(self, **k):
        pass

    def click(self, **k):
        pass

    def approach_enemy(self):
        pass

    def log_info(self, *a, **k):
        pass

    def log_error(self, *a, **k):
        pass

    # ── 配置 ──
    def get_battle_config(self, key, default=None):
        return self._cfg.get(key, default)

    def _parse_skill_sequence(self, raw):
        if not raw:
            return ["1", "2", "3"]
        return [t.strip() for t in str(raw).replace("，", ",").split(",") if t.strip()]

    # ── 检测 ──
    def get_skill_bar_count(self):
        if isinstance(self._skill, list):
            idx = min(self._frame, len(self._skill) - 1)
            return self._skill[idx]
        return self._skill

    def find_one(self, name, **k):
        if name.startswith("ult_"):
            return True if name[4:] in self._ults else None
        if name == "default_link_skill":
            return True if self._link else None
        return None

    # ── 动作 ──
    def use_ult(self, ult_sequence=None):
        ults = [ult_sequence] if ult_sequence else ["1", "2", "3", "4"]
        for u in ults:
            if u in self._ults:
                self.actions.append(f"ult_{u}")
                self.ult_fired_at_frame = self._frame
                self._ults.discard(u)  # 模拟真实消耗：释放后指示消失
                return True
        return False

    def use_link_skill(self):
        if self._link:
            self.actions.append("e")
            self.link_fired_at_frame = self._frame
            self._link = False  # 模拟真实消耗：释放后指示消失
            return True
        return False

    def send_key(self, key):
        self.actions.append(key)
        if self.send_key_consumes and isinstance(self._skill, list):
            # 发键消耗 1 点技力（仅对按帧变化的 list 生效；int 恒定不受影响）
            self._skill[self._frame] = max(0, self._skill[self._frame] - 1)

    def press_combat_key(self, key):
        self.actions.append(key)


class TestConditionalRotationCombat(unittest.TestCase):
    """AutoCombatLogic.run() 实时条件路径集成测试（mock task）。"""

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_conditional_rotation_executes_then_branch(self, _mu, _md):
        cfg = {
            "启用实时条件": True,
            "实时条件序列": ["1", {"if": "link", "then": ["e"]}],
        }
        task = _FakeTask(cfg, ults=(), link=True, skill=3)
        logic = AutoCombatLogic(task)
        logic.run(start_sleep=0)
        self.assertIn("1", task.actions)
        self.assertIn("e", task.actions)

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_conditional_rotation_else_branch(self, _mu, _md):
        cfg = {
            "启用实时条件": True,
            "实时条件序列": [{"if": "link", "then": ["e"], "else": ["2"]}],
        }
        task = _FakeTask(cfg, ults=(), link=False, skill=3)
        logic = AutoCombatLogic(task)
        logic.run(start_sleep=0)
        self.assertIn("2", task.actions)
        self.assertNotIn("e", task.actions)

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_conditional_rotation_empty_falls_back_to_normal(self, _mu, _md):
        cfg = {
            "启用实时条件": True,
            "实时条件序列": [],
            "技能释放": ["1", "2", "3"],
            "启动技能点数": 2,
        }
        task = _FakeTask(cfg, ults=(), link=False, skill=3)
        logic = AutoCombatLogic(task)
        logic.run(start_sleep=0)
        # 回退普通模式：cond_rotation_enabled 最终为 False，走 _do_normal_combat_frame
        self.assertFalse(logic.cond_rotation_enabled)
        self.assertIn("1", task.actions)

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_conditional_rotation_no_match_runs_clean(self, _mu, _md):
        cfg = {
            "启用实时条件": True,
            "实时条件序列": [{"if": "link", "then": ["e"]}],
        }
        task = _FakeTask(cfg, ults=(), link=False, skill=3)
        logic = AutoCombatLogic(task)
        logic.run(start_sleep=0)
        # 条件不满足且无 else：不执行任何动作，但不崩
        self.assertNotIn("e", task.actions)

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_conditional_rotation_ult_action(self, _mu, _md):
        cfg = {
            "启用实时条件": True,
            "实时条件序列": [{"if": "ult2", "then": ["ult_2"]}],
        }
        task = _FakeTask(cfg, ults=[2], link=False, skill=3)
        logic = AutoCombatLogic(task)
        logic.run(start_sleep=0)
        self.assertIn("ult_2", task.actions)

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_instant_ult_release_when_no_cond_action(self, _mu, _md):
        """条件不满足、本帧无动作时，立即释放终结技生效。"""
        cfg = {
            "启用实时条件": True,
            "实时条件序列": [{"if": "link", "then": ["e"]}],  # link 不可用 → 无动作
            "立即释放终结技": True,
        }
        task = _FakeTask(cfg, ults=[2], link=False, skill=3)
        logic = AutoCombatLogic(task)
        logic.run(start_sleep=0)
        self.assertIn("ult_2", task.actions)
        self.assertNotIn("e", task.actions)

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_instant_link_release_when_no_cond_action(self, _mu, _md):
        """条件不满足、本帧无动作时，立即释放连携技生效。"""
        cfg = {
            "启用实时条件": True,
            "实时条件序列": [{"if": "ult2", "then": ["ult_2"]}],  # ult2 不可用 → 无动作
            "立即释放连携技": True,
        }
        task = _FakeTask(cfg, ults=(), link=True, skill=3)
        logic = AutoCombatLogic(task)
        logic.run(start_sleep=0)
        self.assertIn("e", task.actions)

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_conditional_rotation_skill_timeout_keeps_next_token(self, _mu, _md):
        """战技技力不足重试超时后，继续下一个动作。"""
        cfg = {
            "启用实时条件": True,
            "实时条件序列": ["1", "e"],
        }
        task = _FakeTask(cfg, ults=(), link=True, skill=0)
        logic = AutoCombatLogic(task)
        logic.run(start_sleep=0)
        self.assertIn("e", task.actions)

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_conditional_rotation_sleep_truncated_by_deadline(self, _mu, _md):
        cfg = {
            "启用实时条件": True,
            "实时条件序列": ["sleep_5"],
            "技能释放": ["1", "2", "3"],
            "启动技能点数": 2,
        }
        task = _FakeTask(cfg, ults=[], link=False, skill=0)
        logic = AutoCombatLogic(task)
        result = logic.run(start_sleep=0, deadline=1.0)
        self.assertFalse(result)

    # ── 修复回归：等待技力期间不得阻断「立即释放」 ────────────────

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_instant_release_not_blocked_while_skill_pending(self, _mu, _md):
        """数字战技技力不足进入 pending 时，首帧即放行立即释放连携技。

        复现修复前的卡死：失败/等待帧 had_action=True 阻断立即释放，
        连携技要等 pending 超时/重建窗口才能释放（落在 '1' 之后）。
        修复后：失败帧即放行 'e'，技力恢复后 '1' 再补放。
        """
        cfg = {
            "启用实时条件": True,
            "实时条件序列": ["1"],
            "立即释放连携技": True,
        }
        # 技力按帧变化：第 3 帧恢复 1 点，发键消耗后回 0
        task = _FakeTask(cfg, ults=(), link=True, skill=[0, 0, 1] + [0] * 20)
        logic = AutoCombatLogic(task)
        logic.run(start_sleep=0)
        # 修复后 actions == ["e", "1"]；修复前为 ["1", "e"]（e 被饿到重建窗口）
        self.assertIn("e", task.actions)
        self.assertIn("1", task.actions)
        self.assertLess(task.actions.index("e"), task.actions.index("1"))

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_instant_ult_release_not_blocked_while_skill_pending(self, _mu, _md):
        """数字战技等待技力期间，立即释放终结技同样首帧放行。"""
        cfg = {
            "启用实时条件": True,
            "实时条件序列": ["1"],
            "立即释放终结技": True,
        }
        task = _FakeTask(cfg, ults=[2], link=False, skill=[0, 0, 1] + [0] * 20)
        logic = AutoCombatLogic(task)
        logic.run(start_sleep=0)
        self.assertIn("ult_2", task.actions)
        self.assertIn("1", task.actions)
        self.assertLess(task.actions.index("ult_2"), task.actions.index("1"))

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_pending_wait_frames_yield_to_instant_release(self, _mu, _md):
        """技力恒不足的等待帧每帧放行立即释放（修复前首个放行窗口在第 6 帧）。"""
        cfg = {
            "启用实时条件": True,
            "实时条件序列": ["1"],
            "立即释放连携技": True,
        }
        task = _FakeTask(cfg, ults=(), link=True, skill=0)  # 技力恒定 0
        logic = AutoCombatLogic(task)
        logic.run(start_sleep=0)
        self.assertIsNotNone(task.link_fired_at_frame)
        # 修复后：失败帧（第 1 帧）即放行；修复前：pending 5 帧超时（第 6 帧）才放行
        self.assertLessEqual(task.link_fired_at_frame, 2)

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_skill_still_retried_after_recovery(self, _mu, _md):
        """回归保护：技力恢复后 pending 补放行为保留（不被过度修复）。"""
        cfg = {
            "启用实时条件": True,
            "实时条件序列": ["1"],
        }
        task = _FakeTask(cfg, ults=(), link=False, skill=[0, 0, 1] + [0] * 20)
        logic = AutoCombatLogic(task)
        logic.run(start_sleep=0)
        self.assertIn("1", task.actions)

    @patch.object(pyautogui, "mouseDown")
    @patch.object(pyautogui, "mouseUp")
    def test_send_key_noop_snapshot(self, _mu, _md):
        """残差快照：发键 no-op（不扣技力）时数字战技恒「成功」，
        立即释放仅能靠重建帧放行（已知残差，Option C 后续加固）。"""
        cfg = {
            "启用实时条件": True,
            "实时条件序列": ["1"],
            "立即释放连携技": True,
        }
        task = _FakeTask(cfg, ults=(), link=True, skill=[1] * 25)
        task.send_key_consumes = False  # 发键被吞：技力不降，'1' 恒成功
        logic = AutoCombatLogic(task)
        logic.run(start_sleep=0)
        self.assertIn("e", task.actions)  # 重建帧放行（每轮 1 次）


if __name__ == "__main__":
    unittest.main()
