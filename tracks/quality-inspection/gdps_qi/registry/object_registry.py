from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from gdps_qi.types import SampleIdentity


@dataclass(frozen=True)
class SlotTemplate:
    slot_id: str
    position_table: Tuple[float, float, float]
    orientation_xyzw: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)


@dataclass(frozen=True)
class GraspTemplate:
    name: str
    t_object_grasp_position: Tuple[float, float, float]
    t_object_grasp_orientation_xyzw: Tuple[float, float, float, float]
    approach_offset_table_m: Tuple[float, float, float] = (0.0, 0.0, 0.08)
    hand: str = "auto"
    min_edge_gap_m: float = 0.0015


@dataclass
class ObjectRegistry:
    """Rigid workstation templates anchored in table_frame."""

    tablet_slots: Dict[int, SlotTemplate] = field(default_factory=dict)
    tube_slots: Dict[int, SlotTemplate] = field(default_factory=dict)
    rotor_slots: Dict[int, SlotTemplate] = field(default_factory=dict)
    samples: Dict[str, SampleIdentity] = field(default_factory=dict)
    grasp_templates: Dict[str, GraspTemplate] = field(default_factory=dict)

    @classmethod
    def default_six_sample_layout(cls) -> "ObjectRegistry":
        reg = cls()
        spacing = 0.035
        for i in range(1, 7):
            x = (i - 1) * spacing
            reg.tablet_slots[i] = SlotTemplate(
                slot_id=f"tablet_slot_{i:02d}",
                position_table=(x, 0.0, 0.002),
            )
            reg.tube_slots[i] = SlotTemplate(
                slot_id=f"tube_slot_{i:02d}",
                position_table=(x, 0.12, 0.05),
            )
            angle = (i - 1) * (np.pi / 3.0)
            reg.rotor_slots[i] = SlotTemplate(
                slot_id=f"rotor_slot_{i:02d}",
                position_table=(0.06 * np.cos(angle), 0.06 * np.sin(angle), 0.02),
            )
            sid = f"{i:02d}"
            reg.samples[sid] = SampleIdentity(
                sample_id=sid,
                tablet_id=sid,
                tray_slot=i,
                tube_id=sid,
            )
        reg.grasp_templates["tablet_edge_pinch"] = GraspTemplate(
            name="tablet_edge_pinch",
            t_object_grasp_position=(0.012, 0.0, 0.001),
            t_object_grasp_orientation_xyzw=(0.0, 0.7071, 0.0, 0.7071),
            approach_offset_table_m=(0.0, 0.0, 0.06),
            hand="auto",
            min_edge_gap_m=0.0012,
        )
        reg.grasp_templates["tube_body"] = GraspTemplate(
            name="tube_body",
            t_object_grasp_position=(0.0, 0.0, 0.03),
            t_object_grasp_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
            hand="left",
        )
        reg.grasp_templates["cap_twist"] = GraspTemplate(
            name="cap_twist",
            t_object_grasp_position=(0.0, 0.0, 0.055),
            t_object_grasp_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
            hand="right",
        )
        return reg

    def get_sample(self, sample_id: str) -> SampleIdentity:
        if sample_id not in self.samples:
            raise KeyError(sample_id)
        return self.samples[sample_id]

    def validate_unique_ids(self) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        ids = [s.sample_id for s in self.samples.values()]
        if len(ids) != len(set(ids)):
            errors.append("duplicate sample_id")
        tablets = [s.tablet_id for s in self.samples.values()]
        if len(tablets) != len(set(tablets)):
            errors.append("duplicate tablet_id")
        tubes = [s.tube_id for s in self.samples.values()]
        if len(tubes) != len(set(tubes)):
            errors.append("duplicate tube_id")
        return (len(errors) == 0, errors)
