# -*- coding: utf-8 -*-
"""LLM 润色回退鲁棒性（mock 故障注入，离线可测）。

覆盖三种故障模式：调用异常（超时/限流）、空响应、正常响应。
回退契约：任何故障都必须回落模板文案（回答非空、trace.via="fallback"），
不得把空字符串当作润色结果透传给用户。
"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "task7/src"))
from agent_cli import ReActAgent  # noqa: E402


class FakeLLM:
    def __init__(self, behavior):
        self.available = True
        self._behavior = behavior

    def complete(self, system, user, temperature=0.4):
        return self._behavior()


class FaultyLLM(FakeLLM):
    def complete(self, system, user, temperature=0.4):
        raise TimeoutError("mock: 请求超时")


class EmptyLLM(FakeLLM):
    def complete(self, system, user, temperature=0.4):
        return "   \n  "


class OkLLM(FakeLLM):
    """忠实润色：从 plan JSON 中取全部站点名回填文本（模拟真实润色保留站点）。"""

    def complete(self, system, user, temperature=0.4):
        import json as _json
        plan = _json.loads(user)
        pois = "、".join(it["poi"] for it in plan.get("itinerary", []))
        return f"【润色文案】为您安排：{pois}（mock）"


class LLMMockTests(unittest.TestCase):
    QUERY = "情侣黄山两日游，想看日出"

    def _run(self, llm):
        agent = ReActAgent(llm)
        return agent.run(self.QUERY)

    def test_timeout_falls_back_to_template(self):
        r = self._run(FaultyLLM(None))
        self.assertTrue(r["answer"].strip(), "异常回退后回答不得为空")
        self.assertTrue(any(t.get("via") == "fallback" for t in r["trace"]))
        plan = r.get("plan") or {}
        self.assertTrue(plan.get("itinerary"), "回退后仍须有行程")

    def test_empty_response_falls_back(self):
        r = self._run(EmptyLLM(None))
        self.assertTrue(r["answer"].strip(), "空响应须回退模板，不得透传空串")
        self.assertTrue(any(t.get("via") == "fallback" for t in r["trace"]))

    def test_poi_loss_falls_back(self):
        """G11：润色文本站点覆盖率不足 60% 时回退模板（防润色遗漏）。"""

        class LossyLLM(FakeLLM):
            def complete(self, system, user, temperature=0.4):
                return "黄山很美，两天玩得很开心，推荐大家去玩。"  # 无站点名

        r = self._run(LossyLLM(None))
        self.assertTrue(r["answer"].strip())
        self.assertTrue(any(t.get("via") == "fallback" for t in r["trace"]),
                        "站点覆盖不足须回退模板")
        self.assertTrue(any("覆盖不足" in t.get("thought", "") for t in r["trace"]))

    def test_normal_response_used(self):
        r = self._run(OkLLM(None))
        self.assertIn("润色文案", r["answer"])
        self.assertTrue(any(t.get("via") == "llm" for t in r["trace"]))


if __name__ == "__main__":
    unittest.main()
