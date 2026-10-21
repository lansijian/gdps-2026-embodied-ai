"""Prompt / function-calling scene builder for the Doubao realtime session.

One station = one scene: persona + station facts + exact narration text + the
allowed function calls.  The model is instructed to stay on the preset facts
(anti-hallucination) and to call a tool for every navigation-relevant intent,
so the guide never relies on phrase matching for the END signal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .stations import Station

DEFAULT_PERSONA = (
    "你是上海市历史博物馆（原跑马总会大楼）的具身智能导览员“小历”。"
    "说话自然、亲切、简洁，用“您”称呼游客，不读列表和 Markdown 符号。"
)

DEFAULT_RULES = (
    "【安全与礼仪】不进入禁区、不触碰展品、不催促游客、不奔跑。\n"
    "【P1 问答规范】先用一句话给结论，最多再补一句细节，不读长列表；资料里没有的事实、价格、场次、临时活动一律不猜，"
    "用下面的拒答话术并建议咨询一层服务台或拨打电话；涉及政治敏感、未公开信息和他人隐私，礼貌拒答并引导回展品与参观服务。"
)

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "request_next_station",
        "description": (
            "游客表达“讲完了/去下一个点/带我去某某地方/前往下一个目标点”时调用。"
            "如果游客说出具体目标，把目标名称填入 target_name；没提就留空表示下一个停留点。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "游客想去的地点或展品名称，没提则留空"},
                "reason": {"type": "string", "description": "一句话说明为什么结束当前讲解"},
            },
            "required": [],
        },
    },
    {
        "name": "stop_narration",
        "description": "游客要求“别讲了/停一下/安静一会/先别说话”时调用，用于立刻停止当前讲解。",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string", "description": "游客的原话或原因"}},
            "required": [],
        },
    },
    {
        "name": "request_recommendation",
        "description": (
            "游客询问周边景点、餐饮、文创、休息点时调用，用于取回可推荐的周边清单。"
        ),
        "parameters": {
            "type": "object",
            "properties": {"category": {"type": "string", "description": "景点/餐饮/文创/休息/全部"}},
            "required": [],
        },
    },
]


@dataclass
class DialogueKnowledge:
    """P1 facts / FAQ + P5 recommendations injected into every scene."""

    venue_facts: Dict[str, List[str]] = field(default_factory=dict)
    faq: List[Dict[str, str]] = field(default_factory=list)
    refusal_rules: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    refusal_text: str = "这个我暂时不确定，可以帮您问服务台，或者打 021-23299999 咨询。"
    safety_notes: List[str] = field(default_factory=list)
    hotwords: List[str] = field(default_factory=list)
    sources: List[Dict[str, str]] = field(default_factory=list)
    verified: str = "unknown"

    @classmethod
    def load(cls, path: Optional[Path]) -> "DialogueKnowledge":
        if path is None or not Path(path).is_file():
            return cls()
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        meta = payload.get("meta") or {}
        faq = [
            {"q": str(item.get("q") or ""), "a": str(item.get("a") or ""), "category": str(item.get("category") or "")}
            for item in payload.get("faq") or []
            if item.get("q") and item.get("a")
        ]
        return cls(
            venue_facts={str(k): [str(x) for x in v] for k, v in (payload.get("venue_facts") or {}).items()},
            faq=faq,
            refusal_rules=[str(x) for x in payload.get("refusal_rules") or []],
            recommendations=[str(x) for x in payload.get("recommendations") or []],
            refusal_text=str(payload.get("refusal_text") or cls().refusal_text),
            safety_notes=[str(x) for x in payload.get("safety_notes") or []],
            hotwords=[str(x) for x in payload.get("hotwords") or []],
            sources=[
                {"title": str(item.get("title") or ""), "url": str(item.get("url") or "")}
                for item in meta.get("sources") or []
            ],
            verified=str(meta.get("verified") or "unknown"),
        )

    def facts_text(self) -> str:
        if not self.venue_facts:
            return "（馆情资料待补，遇到具体事实问题请用拒答话术）"
        lines = []
        for category, facts in self.venue_facts.items():
            for fact in facts:
                lines.append("- %s：%s" % (category, fact))
        return "\n".join(lines)

    def faq_text(self, max_items: int = 12) -> str:
        if not self.faq:
            return ""
        lines = []
        for item in self.faq[:max_items]:
            lines.append("- 问：%s 答：%s" % (item["q"], item["a"]))
        return "\n".join(lines)

    def refusal_rules_text(self) -> str:
        lines = ["拒答话术：%s" % self.refusal_text]
        for rule in self.refusal_rules:
            lines.append("- %s" % rule)
        return "\n".join(lines)

    def recommendations_text(self) -> str:
        if not self.recommendations:
            return "（周边推荐清单待补）"
        return "\n".join("- " + item for item in self.recommendations)


@dataclass
class SceneText:
    instructions: str
    tools: List[Dict[str, Any]]
    narration_text: str = ""


def _truncate(text: str, budget: int) -> str:
    if len(text) <= budget:
        return text
    return text[: max(0, budget - 1)] + "…"


def build_station_scene(
    station: Station,
    *,
    exhibit_title: str = "",
    narration: str = "",
    short_summary: str = "",
    knowledge: Optional[DialogueKnowledge] = None,
    persona: str = DEFAULT_PERSONA,
    rules: str = DEFAULT_RULES,
    budget: int = 6000,
) -> SceneText:
    """Build the full instructions for one station (called on arrival)."""

    knowledge = knowledge or DialogueKnowledge()
    blocks = [
        persona,
        rules,
        "【当前场景】您正站在“%s”（%s）。" % (station.name, station.kind),
    ]
    if station.area:
        blocks.append("【位置】%s" % station.area)
    if exhibit_title:
        blocks.append("【讲解对象】%s" % exhibit_title)
    if short_summary:
        blocks.append("【一句话要点】%s" % short_summary)
    if narration:
        blocks.append(
            "【预置讲解词（必须按此内容讲，不要改写事实）】\n%s" % narration.strip()
        )
    if station.route_brief:
        blocks.append("【沿途简讲】%s" % station.route_brief)
    blocks.append("【场馆资料（P1 问询依据）】\n" + knowledge.facts_text())
    faq = knowledge.faq_text(8)
    if faq:
        blocks.append("【常见问询速查（优先按这里回答）】\n" + faq)
    blocks.append("【拒答规则】\n" + knowledge.refusal_rules_text())
    blocks.append("【周边推荐（P5）】\n" + knowledge.recommendations_text())
    blocks.append(
        "【结束规则】游客说“好的/谢谢/请前往下一个目标点/带我去下一个点”时，立即调用 request_next_station 工具；"
        "游客要求停止讲话时调用 stop_narration。不要用自然语言回答“好的我这就去”，必须通过工具调用表达。"
    )
    instructions = _truncate("\n\n".join(blocks), budget)
    return SceneText(instructions=instructions, tools=[dict(tool) for tool in TOOLS], narration_text=narration)


def build_route_scene(
    *,
    next_station: Optional[Station] = None,
    knowledge: Optional[DialogueKnowledge] = None,
    persona: str = DEFAULT_PERSONA,
    rules: str = DEFAULT_RULES,
    budget: int = 4000,
) -> SceneText:
    """Scene used while walking between stations (P1 chat + P3 briefs + P2 requests)."""

    knowledge = knowledge or DialogueKnowledge()
    destination = "下一站：%s" % next_station.name if next_station else "当前为自由问询模式"
    blocks = [
        persona,
        rules,
        "【当前场景】您正陪游客在馆内行走，%s。" % destination,
        "【行为要求】行走中只做简短交流；游客问展品/馆情按资料回答，不要长篇大论。",
        "【场馆资料（P1 问询依据）】\n" + knowledge.facts_text(),
        "【常见问询速查（P1）】\n" + (knowledge.faq_text(15) or "（无）"),
        "【拒答规则】\n" + knowledge.refusal_rules_text(),
        "【周边推荐（P5）】\n" + knowledge.recommendations_text(),
        "【结束规则】游客表达“去下一个点/带我去某处/停下”时，必须调用 request_next_station 或 stop_narration。",
    ]
    return SceneText(instructions=_truncate("\n\n".join(blocks), budget), tools=[dict(tool) for tool in TOOLS])


def build_greeting_scene(
    *,
    knowledge: Optional[DialogueKnowledge] = None,
    persona: str = DEFAULT_PERSONA,
    rules: str = DEFAULT_RULES,
    budget: int = 3000,
) -> SceneText:
    """Opening scene: greet the visitor and collect four basic needs (P1 intake)."""

    knowledge = knowledge or DialogueKnowledge()
    blocks = [
        persona,
        rules,
        "【当前场景】游客刚来到面前，请主动打招呼，并用一两句话确认需求："
        "是想整体参观、重点看某件展品，还是先问一些参观信息。",
        "【场馆资料（P1 问询依据）】\n" + knowledge.facts_text(),
        "【常见问询速查（P1）】\n" + (knowledge.faq_text(8) or "（无）"),
        "【拒答规则】\n" + knowledge.refusal_rules_text(),
        "【结束规则】游客说出目的地或“开始吧”时，调用 request_next_station 并填写 target_name（没提就留空）。",
    ]
    return SceneText(instructions=_truncate("\n\n".join(blocks), budget), tools=[dict(tool) for tool in TOOLS])


def tool_result_text(name: str, ok: bool, detail: str = "") -> str:
    """Text returned to the model after a function call executes."""

    if name == "request_next_station":
        return ("正在前往%s" % detail) if ok else ("现在无法前往%s（%s）" % (detail or "未知", detail))
    if name == "stop_narration":
        return "已停止当前讲解。"
    if name == "request_recommendation":
        return detail or "暂无推荐清单。"
    return "已完成。"


__all__ = [
    "DEFAULT_PERSONA",
    "DEFAULT_RULES",
    "TOOLS",
    "DialogueKnowledge",
    "SceneText",
    "build_station_scene",
    "build_route_scene",
    "build_greeting_scene",
    "tool_result_text",
]
