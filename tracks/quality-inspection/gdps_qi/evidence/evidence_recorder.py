from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from gdps_qi.types import ActionEvidence


@dataclass
class EvidenceRecorder:
    output_dir: Path = field(default_factory=lambda: Path("logs/quality-inspection"))
    _events: List[ActionEvidence] = field(default_factory=list)

    def record(self, evidence: ActionEvidence) -> None:
        self._events.append(evidence)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{evidence.task_id}.json"
        path.write_text(json.dumps(evidence.payload | {
            "task_id": evidence.task_id,
            "sample_id": evidence.sample_id,
            "phase": evidence.phase,
            "tf_version": evidence.tf_version,
            "started_at": evidence.started_at,
            "ended_at": evidence.ended_at,
            "result": evidence.result,
            "failure_reason": evidence.failure_reason,
        }, indent=2), encoding="utf-8")

    @property
    def events(self) -> List[ActionEvidence]:
        return list(self._events)
