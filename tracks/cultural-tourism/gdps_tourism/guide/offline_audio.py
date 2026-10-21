"""Offline narration fallback: play pre-generated wav files when Doubao is down.

The competition network may fail or the Doubao quota may run out mid-tour.  The
guide must still narrate the station content and keep the navigation workflow
alive, so we pre-generate every narration / route brief as a wav at build time
(scripts/tourism/prepare_fallback_audio.py) and play it locally.

Manifest format (JSON):
  {"<sha1(text)[:16]>": {"file": "abc.wav", "duration_s": 42.3, "kind": "narration", "id": "EXH_001"}}
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol

from .scene import SceneText


def text_key(text: str) -> str:
    return hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()[:16]


def load_manifest(path: Path | str) -> Dict[str, Dict[str, Any]]:
    manifest_path = Path(path)
    if not manifest_path.is_file():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def wav_duration_s(path: Path) -> float:
    import wave

    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
        return float(frames) / float(rate) if rate else 0.0
    except Exception:
        return 0.0


class Player(Protocol):
    def play(self, path: Path) -> Any: ...
    def stop(self) -> None: ...


class SubprocessPlayer:
    """afplay on macOS, aplay/paplay on Linux."""

    def __init__(self) -> None:
        self._process = None

    def _command(self, path: Path):
        if sys.platform == "darwin":
            return ["afplay", str(path)]
        for binary in ("aplay", "paplay"):
            if shutil.which(binary):
                if binary == "aplay":
                    return [binary, "-q", str(path)]
                return [binary, str(path)]
        return None

    def play(self, path: Path) -> Any:
        command = self._command(path)
        if command is None:
            return None
        self._process = subprocess.Popen(command)
        return self._process

    def stop(self) -> None:
        if self._process is not None:
            try:
                self._process.terminate()
            except Exception:
                pass
            self._process = None


@dataclass
class OfflineAudioDialogue:
    """DialoguePort implementation backed by pre-generated wav files."""

    audio_dir: Path
    manifest: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    player: Any = field(default_factory=SubprocessPlayer)
    on_finished: Optional[Callable[[], Awaitable[None]]] = None
    on_missing: Optional[Callable[[str], None]] = None
    degraded: bool = True
    _task: Optional["asyncio.Task[Any]"] = None

    @classmethod
    def from_dir(
        cls,
        audio_dir: Path | str,
        manifest_name: str = "manifest.json",
        player: Any = None,
    ) -> "OfflineAudioDialogue":
        base = Path(audio_dir)
        manifest = load_manifest(base / manifest_name)
        return cls(audio_dir=base, manifest=manifest, player=player or SubprocessPlayer())

    def has_text(self, text: str) -> bool:
        return text_key(text) in self.manifest

    async def update_scene(self, scene: SceneText) -> None:
        return None

    async def narrate(self, text: str) -> None:
        entry = self.manifest.get(text_key(text))
        if not entry:
            if self.on_missing is not None:
                self.on_missing(text)
            return
        path = self.audio_dir / str(entry.get("file"))
        if not path.is_file():
            if self.on_missing is not None:
                self.on_missing(text)
            return
        self.player.play(path)
        duration = float(entry.get("duration_s") or 0.0)
        await asyncio.sleep(max(0.0, duration))
        if self.on_finished is not None:
            await self.on_finished()

    async def speak_brief(self, text: str) -> None:
        await self.narrate(text)

    async def cancel_speech(self) -> None:
        self.player.stop()

    async def listen(self) -> None:
        return None


class FallbackDialogue:
    """Try the cloud dialogue first, switch permanently to offline wav on failure."""

    def __init__(self, primary, offline: OfflineAudioDialogue) -> None:
        self.primary = primary
        self.offline = offline
        self.degraded = False

    async def update_scene(self, scene: SceneText) -> None:
        if not self.degraded:
            try:
                await self.primary.update_scene(scene)
                return
            except Exception:
                self.degraded = True
        await self.offline.update_scene(scene)

    async def narrate(self, text: str) -> None:
        if not self.degraded:
            try:
                await self.primary.narrate(text)
                return
            except Exception:
                self.degraded = True
        await self.offline.narrate(text)

    async def speak_brief(self, text: str) -> None:
        if not self.degraded:
            try:
                await self.primary.speak_brief(text)
                return
            except Exception:
                self.degraded = True
        await self.offline.speak_brief(text)

    async def cancel_speech(self) -> None:
        try:
            await self.primary.cancel_speech()
        except Exception:
            pass
        await self.offline.cancel_speech()

    async def listen(self) -> None:
        if not self.degraded:
            try:
                await self.primary.listen()
                return
            except Exception:
                self.degraded = True
        await self.offline.listen()


__all__ = [
    "text_key",
    "load_manifest",
    "wav_duration_s",
    "SubprocessPlayer",
    "OfflineAudioDialogue",
    "FallbackDialogue",
]
