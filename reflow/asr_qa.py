#!/usr/bin/env python3
"""语音提问 → ASR → 检索回答 → 写 qa 事件（P2）。

设计原则：**不内置重型依赖**。任何能把音频转成文字的本地/命令行引擎都可以用：
whisper.cpp（whisper-cli）、faster-whisper、vosk、云端 CLI 等，只要提供一条命令模板。

占位符：{audio} 音频路径、{lang} 语种、{out} 输出前缀（部分引擎会写 <out>.txt）。

示例
----
# whisper.cpp（macOS: brew install whisper-cpp；模型放本地）
export GDPS_ASR_CMD="whisper-cli -m /path/ggml-base.bin -f {audio} -l {lang} -otxt -of {out}"
python3 reflow/asr_qa.py --audio logs/q.wav --events-jsonl logs/qa.events.jsonl

# 本地测试（任意命令输出即转写文本）
python3 reflow/asr_qa.py --audio logs/q.wav --asr-cmd "echo 徐光启是谁" \
    --events-jsonl logs/qa.events.jsonl

# 现场录音（需 ffmpeg / arecord / sox 之一）
python3 reflow/asr_qa.py --record 5 --events-jsonl logs/qa.events.jsonl
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

def _load_qa():
    """延迟加载问答依赖（交付包内的 guide_cli / similarity_matcher）。

    仓库分支若未移植这两个模块，仍可用本脚本做转写；真正问答时会给出明确提示。
    """
    try:
        from guide_cli import EventWriter, ask_and_emit  # noqa: F401
        from similarity_matcher import get_matcher  # noqa: F401
    except ImportError as exc:
        die(
            "缺少问答模块（guide_cli.py / similarity_matcher.py）：%r。"
            "可先只做转写；或把这些模块一并移植后再用。" % (exc,)
        )
    return EventWriter, ask_and_emit, get_matcher

ASR_INSTALL_HINT = """未找到可用的 ASR 命令。任选其一：
  * whisper.cpp: brew install whisper-cpp（或编译），下载 ggml 模型后：
      export GDPS_ASR_CMD="whisper-cli -m /path/ggml-base.bin -f {audio} -l {lang} -otxt -of {out}"
  * faster-whisper: pip install faster-whisper，自写 3 行包装脚本，输出转写文本；
  * vosk: pip install vosk，自写包装脚本；
  * 云端 CLI：任何 asr-cmd 能打印文本的命令均可（例如 --asr-cmd "xxx {audio}"）。
测试可先用: --asr-cmd "echo 徐光启是谁"
"""


def die(msg: str, code: int = 2) -> None:
    print("[FAIL] " + str(msg), file=sys.stderr)
    raise SystemExit(code)


def which_recorder():
    if shutil.which("ffmpeg"):
        if sys.platform == "darwin":
            return ["ffmpeg", "-y", "-f", "avfoundation", "-i", ":0"]
        return ["ffmpeg", "-y", "-f", "alsa", "-i", "default"]
    if shutil.which("arecord"):
        return ["arecord", "-q", "-f", "cd"]
    if shutil.which("rec"):
        return ["rec", "-q"]
    return None


def record_audio(seconds: float, out: Path) -> None:
    base = which_recorder()
    if base is None:
        die("找不到录音工具（ffmpeg / arecord / sox）。请改用 --audio 传入已录好的音频。")
    out.parent.mkdir(parents=True, exist_ok=True)
    if base[0] == "ffmpeg":
        cmd = base + ["-t", str(seconds), str(out)]
    elif base[0] == "arecord":
        cmd = base + ["-d", str(seconds), str(out)]
    else:  # rec
        cmd = base + [str(out), "trim", "0", str(seconds)]
    print("[asr] 录音 %.1fs → %s（说完请稍候）" % (seconds, out), file=sys.stderr, flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        die("录音失败：%s" % (proc.stderr.strip() or "输出文件为空"))


def transcribe(cmd_template: str, audio: Path, lang: str, out_base: Path, timeout: float):
    parts = shlex.split(cmd_template)
    if not parts:
        die("ASR 命令为空")
    rendered = [
        part.replace("{audio}", str(audio)).replace("{lang}", lang).replace("{out}", str(out_base))
        for part in parts
    ]
    started = time.perf_counter()
    try:
        proc = subprocess.run(rendered, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        die("ASR 超时（>%.0fs）：%s" % (timeout, " ".join(rendered)))
    elapsed = round(time.perf_counter() - started, 3)
    text = (proc.stdout or "").strip()
    if not text:
        for candidate in (Path(str(out_base) + ".txt"), audio.with_suffix(".txt")):
            if candidate.is_file():
                text = candidate.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    break
    if not text:
        die("ASR 无输出（返回码 %s）：%s" % (proc.returncode, (proc.stderr or "").strip()[:400]))
    return text, elapsed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="语音提问 → ASR → 检索回答 → qa 事件")
    parser.add_argument("--audio", default="", help="已录好的音频文件（wav/mp3 等，取决于 ASR 引擎）")
    parser.add_argument("--record", type=float, default=0.0, help="现场录音秒数（需 ffmpeg/arecord/sox）")
    parser.add_argument("--out", default="logs/asr_question.wav", help="--record 的输出路径")
    parser.add_argument("--asr-cmd", default=os.environ.get("GDPS_ASR_CMD", ""), help="ASR 命令模板，可用环境变量 GDPS_ASR_CMD")
    parser.add_argument("--lang", default="zh")
    parser.add_argument("--asr-timeout", type=float, default=60.0)
    parser.add_argument("--events-jsonl", required=True, help="qa 事件输出文件（供 reflow/agent.py 合并）")
    parser.add_argument("--short", action="store_true", help="使用 10 秒速览讲解")
    parser.add_argument("--quiet", action="store_true", help="不打印讲解词")
    args = parser.parse_args(argv)

    if not args.audio and args.record <= 0:
        die("需要 --audio <文件> 或 --record <秒数>")
    if not args.asr_cmd:
        die(ASR_INSTALL_HINT)

    if args.record > 0 and not args.audio:
        audio = Path(args.out)
        record_audio(args.record, audio)
    else:
        audio = Path(args.audio)
    if not audio.is_file():
        die("音频文件不存在：%s" % audio)

    out_base = audio.with_suffix("")
    text, asr_latency = transcribe(args.asr_cmd, audio, args.lang, out_base, args.asr_timeout)
    print("[asr] %.2fs 转写：%s" % (asr_latency, text), file=sys.stderr, flush=True)

    EventWriter, ask_and_emit, get_matcher = _load_qa()
    writer = EventWriter(args.events_jsonl)
    try:
        writer.emit(
            "asr_transcript",
            text=text,
            audio=str(audio),
            backend=shlex.split(args.asr_cmd)[0],
            asr_latency_s=asr_latency,
        )
        matcher = get_matcher()
        hit = ask_and_emit(
            matcher,
            text,
            writer,
            args.short,
            print_output=not args.quiet,
            extra_details={
                "question_source": "asr",
                "asr": {
                    "text": text,
                    "backend": shlex.split(args.asr_cmd)[0],
                    "latency_s": asr_latency,
                    "audio": str(audio),
                },
            },
        )
    finally:
        writer.close()
    print("[events] 已写入 %d 条事件：%s" % (writer.count, writer.path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
