#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
G1 机器人 + 豆包端到端实时语音大模型 对话 Demo（宇树官方 SDK 版）

完整链路：
    G1 四麦阵列 (UDP 组播 239.168.123.161:5555, 16kHz/s16le/单声道)
        -> 豆包云端 (ASR -> LLM -> TTS, 24kHz/s16le/单声道)
        -> 重采样到 16kHz -> G1 喇叭 (AudioClient.PlayStream)

==================== 使用步骤 ====================
1. 依赖（在机器人上执行）：
       pip3 install websockets numpy
   宇树 SDK（G1 一般已预装 unitree_sdk2py，没有的话）：
       git clone https://github.com/unitreerobotics/unitree_sdk2_python
       cd unitree_sdk2_python && pip3 install -e .

2. 配置临时 API Key（只在当前 SSH 窗口有效，关窗即失效，不落盘）：
       export DOUBAO_API_KEY="你的key"

3. 运行：
       python3 g1_doubao_voice.py

   看到「会话已建立」后直接对机器人说话即可；请等豆包说完再开口
   （播音期间麦克风上行会被静音，防止回声误触发）。Ctrl+C 退出。

==================== 排障速查 ====================
- 收不到麦克风数据：确认机器人语音服务(Vui_Service)在运行；用遥控器
  按 L1+L2 把语音交互切到「唤醒模式」——麦克风只在交互开启时推组播流。
- PlayStream/GetVolume 报错 send request error：DDS 没连上语音服务，
  确认本机网卡在 192.168.123.x 网段、能 ping 通 192.168.123.161。
- 回声自激（喇叭声音回灌麦克风）：机器人端语音服务自带 AEC，
  若仍明显，调低音量（脚本里 VOLUME 改小）。
==================================================
"""

import asyncio
import base64
import inspect
import json
import os
import queue
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid

import numpy as np
import websockets

try:
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
except ImportError:
    sys.exit("未找到 unitree_sdk2py，请先安装宇树 Python SDK：\n"
             "  git clone https://github.com/unitreerobotics/unitree_sdk2_python\n"
             "  cd unitree_sdk2_python && pip3 install -e .")

# ----------------- 可按需修改的配置 -----------------
WS_URL = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"
MODEL = "1.2.6.1"                                   # Seeduplex 3.0 全双工模型版本（固定值）
VOICE = os.environ.get("DOUBAO_VOICE", "zh_female_vv_jupiter_bigtts")  # 音色
INSTRUCTIONS = (
    "你是一个装在机器人上的语音助手，叫小豆。说话口语化、简洁，"
    "每次回答尽量控制在两句话以内，不要读列表和符号。"
)
VOLUME = 100            # G1 喇叭音量 0-100
GREETING = "你好，我是小豆。喇叭和云端语音链路都正常。"   # 启动后自动播报, 用于验证下行链路

# G1 音频规格（官方固定，勿改）
MCAST_GROUP = "239.168.123.161"   # 麦克风组播地址
MCAST_PORT = 5555                 # 麦克风组播端口
G1_RATE = 16000                   # 喇叭 PlayStream / 麦克风组播 均为 16kHz

# 豆包音频规格
INPUT_RATE = 16000     # 上行：与 G1 麦克风一致，直通
OUTPUT_RATE = 24000    # 下行：模型合成固定 24kHz，需重采样到 16kHz 喂喇叭

PLAY_CHUNK_MS = 50     # 每 50ms 喂一次喇叭（1600 字节 @16k，社区实测最稳）
APP_NAME = "doubao"    # PlayStream 的 app 标识（多应用互不干扰用）
# ----------------------------------------------------

mic_q: "queue.Queue[bytes]" = queue.Queue()   # 麦克风数据队列
play_buf = bytearray()                         # 待播放音频缓冲（24kHz）
play_lock = threading.Lock()
running = True
g1_audio = None                                # AudioClient 实例（main 里初始化）
play_stream_id = "boot"   # 当前播报流 ID：同一轮语音共用, 每块都换会被语音服务反复抢占
mute_until = 0.0          # 单调时钟: 此时间戳之前上行发静音(播音期间防回声自激)
played_any = False        # 本轮是否已送出首块喇叭音频（日志用）
rx_bytes = [0]            # 本轮已收云端音频字节数（日志用）


# ============== G1 麦克风：UDP 组播接收 ==============
def get_123_iface():
    """自动找 192.168.123.x 网段的网卡名和本机 IP（DDS 和组播都要用）"""
    out = subprocess.check_output(["ip", "-o", "-4", "addr", "show"]).decode()
    for line in out.splitlines():
        parts = line.split()
        iface, ip = parts[1], parts[3].split("/")[0]
        if ip.startswith("192.168.123."):
            return iface, ip
    sys.exit("❌ 没找到 192.168.123.x 网段的网卡，检查网线连接和 IP 配置")


def mic_thread(local_ip):
    """加入组播组，把收到的 PCM 包（每包 5120 字节=160ms）放进队列"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", MCAST_PORT))
    mreq = struct.pack("4s4s", socket.inet_aton(MCAST_GROUP), socket.inet_aton(local_ip))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    print(f"🎙  已加入麦克风组播 {MCAST_GROUP}:{MCAST_PORT} (iface ip={local_ip})")
    got = False
    while running:
        data, _ = sock.recvfrom(8192)
        if not got:
            print("🎙  麦克风音频流已接通")
            got = True
        mic_q.put(data)


# ============== G1 喇叭：重采样 + PlayStream 分块播放 ==============
def resample_24k_to_16k(pcm: bytes) -> bytes:
    """豆包下行 24kHz -> G1 喇叭 16kHz（3:2 线性插值）"""
    x = np.frombuffer(pcm, dtype=np.int16)
    n = len(x)
    if n == 0:
        return b""
    idx = np.linspace(0, n - 1, n * 2 // 3)
    return np.interp(idx, np.arange(n), x.astype(np.float32)).astype(np.int16).tobytes()


def player_thread():
    """从缓冲取 24kHz 音频，重采样后按 50ms 一块喂给 G1 喇叭"""
    global mute_until, played_any
    need_16k_bytes = int(G1_RATE * PLAY_CHUNK_MS / 1000) * 2   # 1600 字节
    need_24k_bytes = need_16k_bytes * 3 // 2                   # 对应 2400 字节
    while running:
        with play_lock:
            if len(play_buf) >= need_24k_bytes:
                chunk24 = bytes(play_buf[:need_24k_bytes])
                del play_buf[:need_24k_bytes]
            else:
                chunk24 = None
        if chunk24 is None:
            time.sleep(0.01)
            continue
        pcm16 = resample_24k_to_16k(chunk24)
        try:
            ret = g1_audio.PlayStream(APP_NAME, play_stream_id, pcm16)   # 官方签名要求 bytes
            code = ret[0] if isinstance(ret, tuple) else ret             # 返回 (code, msg), 0=成功
            if code != 0:
                now = time.monotonic()
                if now - getattr(player_thread, "_last_err_t", 0.0) > 2.0:   # 限频，最多2秒一条
                    player_thread._last_err_t = now
                    print(f"\n⚠️  PlayStream 返回错误: {ret}")
        except Exception as e:
            print(f"\n⚠️  PlayStream 异常: {e}")
        if not played_any:
            print("🔊 已向喇叭送出第一块音频")
            played_any = True
        mute_until = time.monotonic() + PLAY_CHUNK_MS / 1000 + 0.3   # 播音期间+300ms拖尾屏蔽上行
        time.sleep(PLAY_CHUNK_MS / 1000)


# ============== 豆包 WebSocket 收发（与原 demo 相同） ==============
async def mic_sender(ws):
    """把麦克风音频按官方要求重打包：20ms/包(640字节)、严格按实时节奏发送。

    G1 组播一包 5120 字节=160ms，直接整包转发会偏离实时节奏，
    导致云端 VAD 不判停、不触发识别 —— 必须拆成 8 帧匀速发。
    每 20ms 必发一帧：队列里有真音频发真音频，没有就发静音
    （官方文档：模型靠上行音频流保活，断流则无响应）。
    注意：不能用 asyncio.to_thread 读队列 —— Python 3.8 没有这个函数，
    且超时遗弃的线程会把麦克风包吃掉。
    """
    FRAME = 640          # 20ms @16kHz int16 单声道
    SILENCE = b"\x00" * FRAME
    buf = b""
    next_t = time.monotonic()
    stat_total = 0       # 本统计周期已发总帧数
    stat_voice = 0       # 其中有明显声音的帧数
    stat_t = time.monotonic()
    while running:
        # 1) 节奏：每 20ms 一个节拍
        next_t += 0.02
        delay = next_t - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        else:
            next_t = time.monotonic()   # 落后太多就重置基准，防止追帧爆发

        # 2) 非阻塞地把队列里积压的组播包全部收进来
        try:
            while True:
                buf += mic_q.get_nowait()
        except queue.Empty:
            pass
        if len(buf) > 51200:            # 积压超过1.6秒就丢旧的，防爆内存/防陈旧音频
            buf = buf[-25600:]

        # 3) 取一帧：够 640 字节用真音频，不够补静音（保活）
        if len(buf) >= FRAME:
            frame, buf = buf[:FRAME], buf[FRAME:]
        else:
            frame = SILENCE
        if time.monotonic() < mute_until:
            frame = SILENCE             # 播音期间上行发静音, 防喇叭回声把自己掐死

        # 4) 发送
        await ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(frame).decode(),
        }))

        # 5) DEBUG 统计：每 5 秒报一次上行情况，肉眼确认声音真的发出去了
        stat_total += 1
        if frame is not SILENCE:
            peak = max(abs(int.from_bytes(frame[k:k+2], "little", signed=True))
                       for k in range(0, FRAME, 20))
            if peak > 500:
                stat_voice += 1
        if os.environ.get("DEBUG") and time.monotonic() - stat_t > 5.0:
            stat_t = time.monotonic()
            print(f"\n[debug] 上行: 5秒发{stat_total}帧, 有声{stat_voice}帧, "
                  f"缓冲积压{len(buf)}字节, 静音中={time.monotonic() < mute_until}")
            stat_total = stat_voice = 0


async def receiver(ws):
    """处理云端推下来的各种事件"""
    global play_stream_id, played_any, mute_until
    asr_text = ""   # 已累计展示的识别文本；服务端 delta 实际是「当前完整识别结果」
    async for raw in ws:
        evt = json.loads(raw)
        t = evt.get("type", "")

        # --- 用户语音识别（ASR）---
        if t == "conversation.item.input_audio_transcription.started":
            # 不做「打断播放」：播音期间上行是静音，此刻云端推来的开口事件
            # 只可能是播音前环境噪音触发的迟到误判；一旦 PlayStop 会把
            # 正在播放的回复整段掐掉（这就是"有🔊日志但喇叭没声"的根因）。
            asr_text = ""
            print("\n🎙  你: ", end="", flush=True)
        elif t == "conversation.item.input_audio_transcription.delta":
            full = evt.get("delta", "")
            if full.startswith(asr_text):
                print(full[len(asr_text):], end="", flush=True)
            else:
                print(f"\r🎙  你: {full}", end="", flush=True)
            asr_text = full
        elif t == "conversation.item.input_audio_transcription.completed":
            print()

        # --- 模型思考（文本，便于观察）---
        elif t == "response.output_text.delta":
            print(evt.get("delta", ""), end="", flush=True)
        elif t == "response.output_text.done":
            print()

        # --- 模型语音（TTS 音频流，24kHz 先存缓冲）---
        elif t == "response.output_audio.started":
            play_stream_id = str(time.time_ns())   # 同一轮语音共用一个流ID
            played_any = False
            mute_until = max(mute_until, time.monotonic() + 2.0)   # 覆盖首块到达前的合成延迟(不缩短已有静音窗)
            rx_bytes[0] = 0
            print("🤖 豆包: ", end="", flush=True)
        elif t == "response.output_audio.delta":
            audio = base64.b64decode(evt.get("delta", ""))
            if rx_bytes[0] == 0:
                print("\n⬇ 已开始接收云端音频")
            rx_bytes[0] += len(audio)
            with play_lock:
                play_buf.extend(audio)
        elif t == "response.output_audio.done":
            print(f"\n   [本轮云端音频共 {rx_bytes[0]} 字节]")

        # --- 一轮结束，带用量信息（计费参考）---
        elif t == "response.done":
            usage = (evt.get("response") or {}).get("usage") or evt.get("usage")
            if usage:
                print(f"   [本轮用量] {json.dumps(usage, ensure_ascii=False)}")

        elif t == "session.closed":
            print("会话已结束")
            break
        elif t == "error":
            print(f"\n❌ 服务端错误: {json.dumps(evt, ensure_ascii=False)}")
        elif os.environ.get("DEBUG"):
            # DEBUG=1 时打印所有未处理事件，排查协议问题用
            print(f"\n[debug] {t}: {raw[:200]}")


async def main():
    global running, g1_audio, mute_until
    api_key = os.environ.get("DOUBAO_API_KEY", "").strip()
    if not api_key:
        sys.exit("请先设置环境变量： export DOUBAO_API_KEY=\"你的key\"")

    # 1) 初始化 G1 音频 SDK
    iface, local_ip = get_123_iface()
    print(f"网卡: {iface}   本机IP: {local_ip}")
    ChannelFactoryInitialize(0, iface)
    g1_audio = AudioClient()
    g1_audio.SetTimeout(10.0)
    g1_audio.Init()
    ret = g1_audio.SetVolume(VOLUME)
    print(f"✅ G1 音频服务已连接，音量设为 {VOLUME} (ret={ret})")

    # 2) 启动麦克风接收线程 + 喇叭播放线程
    threading.Thread(target=mic_thread, args=(local_ip,), daemon=True).start()
    threading.Thread(target=player_thread, daemon=True).start()

    # 3) 连豆包，进入全双工对话
    headers = {
        "X-Api-Key": api_key,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    print("正在连接豆包实时语音服务 ...")
    # 兼容新旧版 websockets：旧版(legacy)用 extra_headers，新版用 additional_headers
    ws_kwargs = {"max_size": None, "ping_interval": 20}
    if "additional_headers" in inspect.signature(websockets.connect).parameters:
        ws_kwargs["additional_headers"] = headers
    else:
        ws_kwargs["extra_headers"] = headers
    async with websockets.connect(WS_URL, **ws_kwargs) as ws:
        await ws.send(json.dumps({
            "type": "session.create",
            "event_id": f"event_{uuid.uuid4().hex}",
            "session": {
                "model": MODEL,
                "instructions": INSTRUCTIONS,
                "audio": {
                    "input":  {"format": {"type": "pcm", "rate": INPUT_RATE}},
                    "output": {"format": {"type": "pcm_s16le", "rate": OUTPUT_RATE},
                               "voice": VOICE, "loudness": 30},
                },
                # 官方示例必带: asr/tts/dialog 三个空对象, 缺了可能导致云端不激活识别/对话管线
                "extension": {"asr": {}, "tts": {}, "dialog": {}},
            },
        }, ensure_ascii=False))

        async for raw in ws:
            evt = json.loads(raw)
            if evt.get("type") == "session.created":
                print(f"✅ 会话已建立 (session id: {evt.get('session', {}).get('id', '')})")
                print("直接对机器人说话吧，Ctrl+C 退出\n")
                break
            if evt.get("type") == "error":
                sys.exit(f"❌ 创建会话失败: {json.dumps(evt, ensure_ascii=False)}")

        # 开场白阶段上行直接发静音帧：既满足「模型依赖上行音频流保活」，
        # 又不让环境噪音在开场白合成期间误触发云端 VAD。
        mute_until = time.monotonic() + 5.0   # 覆盖到 output_audio.started 接管为止
        sender = asyncio.create_task(mic_sender(ws))
        await asyncio.sleep(1.0)   # 先让上行音频流起来(模型依赖上行保活, 断流则无响应)

        # 3.5) 开机自报家门: 让云端合成一句话从机器人喇叭播出
        #      —— 顺便验证「豆包 -> 重采样 -> PlayStream -> G1 喇叭」整条下行链路
        print(f"🔊 尝试播报开场白: 「{GREETING}」")
        await ws.send(json.dumps({
            "type": "speech_text_buffer.commit",
            "event_id": f"event_{uuid.uuid4().hex}",
            "text": GREETING,          # 官方文档: 字段名是 text
        }, ensure_ascii=False))
        try:
            await receiver(ws)
        finally:
            running = False
            sender.cancel()
            try:
                g1_audio.PlayStop(APP_NAME)
            except Exception:
                pass
            await ws.send(json.dumps({"type": "session.close"}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n再见 👋")
