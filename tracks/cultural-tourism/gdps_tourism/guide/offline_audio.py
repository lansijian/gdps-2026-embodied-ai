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


class G1WavPlayer:
    """Play fallback wav files through the G1 voice service (free, no cloud).

    The robot speaker is routed through Unitree's voice service, not ALSA, so
    SubprocessPlayer (aplay/paplay) cannot reach it.  This player decodes the wav
    to 24 kHz mono int16 and feeds G1AudioIO, which calls AudioClient.PlayStream.
    """

    def __init__(self, volume: int = 80) -> None:
        self.volume = int(volume)
        self._io = None

    def _ensure(self):
        if self._io is None:
            from .doubao_realtime import G1AudioIO

            io = G1AudioIO(volume=self.volume)
            io.start()
            self._io = io
        return self._io

    @staticmethod
    def _load_pcm24(path: Path) -> bytes:
        import wave

        import numpy as np

        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            raw = handle.readframes(handle.getnframes())
        if width != 2:
            return b""
        samples = np.frombuffer(raw, dtype=np.int16)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
        if rate != 24000 and len(samples) > 1:
            count = max(1, int(round(len(samples) * 24000.0 / rate)))
            index = np.linspace(0, len(samples) - 1, count)
            samples = np.interp(index, np.arange(len(samples)), samples.astype(np.float32)).astype(np.int16)
        return samples.tobytes()

    def play(self, path: Path) -> Any:
        io = self._ensure()
        pcm = self._load_pcm24(Path(path))
        if pcm:
            io.play(pcm)
        return None

    def stop(self) -> None:
        if self._io is not None:
            self._io.stop_playback()

    def close(self) -> None:
        if self._io is not None:
            self._io.stop()
            self._io = None


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
    "G1WavPlayer",
    "OfflineAudioDialogue",
    "FallbackDialogue",
]
