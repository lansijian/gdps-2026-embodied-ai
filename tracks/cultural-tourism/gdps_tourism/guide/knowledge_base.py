"""knowledge_base.json loader for the guide (titles / narration / hotwords)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ExhibitKnowledge:
    titles: Dict[str, str] = field(default_factory=dict)
    narrations: Dict[str, str] = field(default_factory=dict)
    short_summaries: Dict[str, str] = field(default_factory=dict)
    hotwords: List[str] = field(default_factory=list)

    def add(self, item: dict) -> None:
        exhibit_id = str(item.get("id") or "")
        if not exhibit_id:
            return
        name = str(item.get("name") or exhibit_id)
        self.titles[exhibit_id] = name
        narration = str(item.get("narration") or "")
        if narration:
            self.narrations[exhibit_id] = narration
        summary = str(item.get("short_summary") or "")
        if summary:
            self.short_summaries[exhibit_id] = summary
        for word in [name] + list(item.get("aliases") or []) + list(item.get("trigger_keywords") or []):
            text = str(word).strip()
            if text and text not in self.hotwords:
                self.hotwords.append(text)


def load_knowledge_base(root: Path | str) -> ExhibitKnowledge:
    """Load knowledge_base.json from a directory or one of its parents."""

    base = Path(root)
    candidates = [base / "knowledge_base.json", base.parent / "knowledge_base.json"]
    for candidate in candidates:
        if candidate.is_file():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            knowledge = ExhibitKnowledge()
            for item in payload.get("exhibits") or []:
                knowledge.add(item)
            for item in payload.get("composite_boards") or []:
                knowledge.add(item)
            return knowledge
    return ExhibitKnowledge()


__all__ = ["ExhibitKnowledge", "load_knowledge_base"]
