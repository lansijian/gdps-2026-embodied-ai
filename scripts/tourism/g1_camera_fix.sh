#!/bin/bash
# ============================================================
# G1 深度相机 (Intel RealSense D435i) 一键修复 / 查看脚本
# 适用: Unitree G1 (Jetson Orin), 相机 USB VID:PID = 8086:0b3a
#
# 用法:
#   bash g1_camera_fix.sh           临时修复(重启失效) + 出流自检
#   bash g1_camera_fix.sh persist   临时修复 + 写入永久配置(重启也生效)
#   bash g1_camera_fix.sh view      30FPS 实时画面(浏览器打开提示的网址)
#   bash g1_camera_fix.sh restore   还原: 删除永久配置(借来的机器还机前用)
#
# 排障口诀:
#   无占用 -> 认到USB -> 有节点 -> 能出流, 四步按顺序过
#   节点消失/报错-71 -> 相机固件挂死, 拔插Type-C断电后重跑本脚本
#   30FPS失败 -> lsusb -t 看速率, 480M=USB2.0降速, 重新插紧Type-C
# ============================================================

VID="8086"
PID="0b3a"
UDEV_RULE="/etc/udev/rules.d/99-realsense-power.rules"
MODPROBE_CONF="/etc/modprobe.d/usbcore.conf"

say() { echo; echo "===== $1 ====="; }

# ---------- 0. 检查 videohub 占用 ----------
check_occupation() {
    say "0. videohub 占用检查"
    if ps aux | grep -i videohub | grep -v grep; then
        echo "⚠️  videohub 正在占用相机(带看门狗, 单纯 pkill 会复活)"
        echo "   自己的机器可执行(会关闭官方图传; 本机二进制在 /unitree/module/video_hub_pc4/):"
        echo "     sudo pkill -9 -f videohub"
        echo "     sudo mv /unitree/module/video_hub_pc4/videohub_pc4 /unitree/module/video_hub_pc4/videohub_pc4.bak"
        echo "   恢复图传: 把上面的 .bak 改回原名并重启 master_service 对应服务"
        echo "   借来的机器建议先和机主确认再动。处理完重跑本脚本。"
        exit 1
    else
        echo "✅ 无占用"
    fi
}

# ---------- 1. 定位相机(按 VID:PID 动态找, 不依赖端口号) ----------
find_cam() {
    say "1. 查找相机 USB 端口"
    CAM_DEV=""
    for d in /sys/bus/usb/devices/*; do
        [ -f "$d/idVendor" ] || continue
        if [ "$(cat "$d/idVendor")" = "$VID" ] && [ "$(cat "$d/idProduct")" = "$PID" ]; then
            CAM_DEV=$(basename "$d")
            break
        fi
    done
    if [ -z "$CAM_DEV" ]; then
        echo "❌ 未找到相机 (VID=$VID PID=$PID)"
        lsusb | grep -i "intel\|$VID" || echo "   lsusb 也看不到 -> 物理连接问题"
        echo "   处理: 拔插一次机身内 Type-C, 然后重跑本脚本"
        exit 1
    fi
    echo "✅ 相机挂载在: $CAM_DEV"
    lsusb -t 2>/dev/null | grep -B1 "Video" | grep -o "[0-9]*M" | head -n1 | \
        xargs -I{} echo "   当前链路速率: {} (5000M=USB3.0正常, 480M=降速)"
}

# ---------- 2. 关闭 USB 省电 + 提升缓冲(运行时, 重启失效) ----------
apply_power() {
    say "2. 关闭 USB 省电 + 提升缓冲"
    PARENT=$(echo "$CAM_DEV" | sed 's/\.[0-9]*$//')   # 2-2.3 -> 2-2 (上级 hub)
    echo -1 | sudo tee /sys/bus/usb/devices/$CAM_DEV/power/autosuspend
    echo on | sudo tee /sys/bus/usb/devices/$CAM_DEV/power/control
    if [ "$PARENT" != "$CAM_DEV" ] && [ -d "/sys/bus/usb/devices/$PARENT" ]; then
        echo -1 | sudo tee /sys/bus/usb/devices/$PARENT/power/autosuspend
    fi
    sudo sh -c 'echo 1000 > /sys/module/usbcore/parameters/usbfs_memory_mb'
    echo "✅ 完成(运行时生效, 重启失效; 永久生效跑: bash $0 persist)"
}

# ---------- 2.5 自动识别彩色节点(不写死 video4) ----------
find_color_node() {
    COLOR_NODE=""
    for candidate in /dev/video4 /dev/video2 /dev/video0 /dev/video*; do
        [ -e "$candidate" ] || continue
        if command -v v4l2-ctl >/dev/null 2>&1; then
            if v4l2-ctl -d "$candidate" --list-formats-ext 2>/dev/null | grep -q "YUYV"; then
                COLOR_NODE="$candidate"
                break
            fi
        else
            COLOR_NODE="$candidate"
            break
        fi
    done
    if [ -z "$COLOR_NODE" ]; then
        echo "⚠️  未找到 YUYV 彩色节点, 保守使用 /dev/video4"
        COLOR_NODE="/dev/video4"
    fi
    echo "✅ 彩色节点: $COLOR_NODE"
}

# ---------- 3. 检查节点 & 出流自检 ----------
verify() {
    say "3. 视频节点检查"
    NODES=$(ls /dev/video* 2>/dev/null)
    if [ -z "$NODES" ]; then
        echo "❌ 无 /dev/video 节点(相机固件可能挂死)"
        echo "   处理: 拔插一次 Type-C 让相机断电重启, 或 sudo reboot, 然后重跑本脚本"
        exit 1
    fi
    echo "$NODES"
    find_color_node
    if command -v gst-launch-1.0 >/dev/null; then
        say "4. 出流自检 ($COLOR_NODE 彩色流, 5秒)"
        ok=0
        for spec in "640 480 30" "640 360 30" "640 480 15"; do
            set -- $spec
            echo "   尝试 width=$1 height=$2 fps=$3 ..."
            if timeout 8 gst-launch-1.0 -q v4l2src device="$COLOR_NODE" num-buffers=20 ! \
                "video/x-raw,format=YUY2,width=$1,height=$2,framerate=$3/1" ! fakesink >/dev/null 2>&1; then
                echo "✅ 出流正常 (width=$1 height=$2 fps=$3)"
                ok=1
                break
            fi
        done
        if [ "$ok" -eq 0 ]; then
            echo "⚠️  出流失败。查链路速率: lsusb -t (480M=USB2.0降速, 重插Type-C)"
            echo "   若内核日志是 -71/device not responding: 拔插 Type-C 后再跑本脚本"
        fi
    fi
}

# ---------- 5. 写入永久配置(udev + modprobe, 按VID:PID匹配不绑端口) ----------
persist() {
    say "5. 写入永久配置"
    echo "ACTION==\"add\", SUBSYSTEM==\"usb\", ATTR{idVendor}==\"$VID\", ATTR{idProduct}==\"$PID\", ATTR{power/autosuspend}=\"-1\", ATTR{power/control}=\"on\"" \
        | sudo tee "$UDEV_RULE"
    echo "options usbcore usbfs_memory_mb=1000" | sudo tee "$MODPROBE_CONF"
    sudo udevadm control --reload && sudo udevadm trigger
    echo "✅ 已永久生效(开机/拔插/换口自动应用, 不影响其他USB设备)"
    echo "   还原方法: bash $0 restore"
}

# ---------- 还原出厂(还机前执行) ----------
restore() {
    say "还原出厂状态"
    sudo rm -f "$UDEV_RULE" "$MODPROBE_CONF"
    sudo udevadm control --reload
    echo "✅ 永久配置已删除"
    echo "   运行时设置断电即消失, 接下来 sudo poweroff 关机即可"
    echo "   下次开机 = 出厂状态, 无任何残留"
}

# ---------- 实时画面(30FPS, 浏览器 MJPEG, 不存盘) ----------
view() {
    check_occupation
    say "实时画面 (640x480@30)"
    IP=$(hostname -I | awk '{print $1}')
    echo "在电脑浏览器打开: http://$IP:8080   (Ctrl+C 退出)"
    COLOR_NODE="$COLOR_NODE" python3 << 'PYEOF'
import cv2, os, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PIPE = "v4l2src device=%s ! video/x-raw,format=YUY2,width=640,height=480,framerate=30/1 ! videoconvert ! queue leaky=downstream max-size-buffers=1 ! appsink" % os.environ.get("COLOR_NODE", "/dev/video4")

latest = [None]
lock = threading.Lock()

def grab(cap):
    n, t0 = 0, time.time()
    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.01); continue
        frame = cv2.flip(frame, -1)   # 画面默认倒置, 翻正
        with lock:
            latest[0] = frame
        n += 1
        if n % 150 == 0:
            print("[OK] frames=%d, %.1f FPS" % (n, n / (time.time() - t0)), flush=True)

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=jpg")
        self.end_headers()
        while True:
            with lock:
                f = None if latest[0] is None else latest[0].copy()
            if f is None:
                time.sleep(0.01); continue
            ok, jpg = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ok: continue
            try:
                self.wfile.write(b"--jpg\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")
            except OSError:
                return
            time.sleep(1/30)
    def log_message(self, *a):
        pass

cap = cv2.VideoCapture(PIPE, cv2.CAP_GSTREAMER)
assert cap.isOpened(), "cannot open colour node"
threading.Thread(target=grab, args=(cap,), daemon=True).start()
ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
PYEOF
}

# ---------- 状态(只读) ----------
status() {
    say "相机状态(只读)"
    echo "-- USB --"
    lsusb | grep -iE "intel|$VID"
    lsusb -t 2>/dev/null | grep -A2 -B1 "Video" | head -8
    echo "-- nodes --"
    ls -l /dev/video* 2>&1 | head -8
    for candidate in /dev/video4 /dev/video2 /dev/video0; do
        [ -e "$candidate" ] || continue
        echo "-- $candidate formats --"
        v4l2-ctl -d "$candidate" --list-formats-ext 2>/dev/null | head -10
    done
    echo "-- power --"
    for d in /sys/bus/usb/devices/2-2.3 /sys/bus/usb/devices/2-2; do
        [ -e "$d/power/control" ] || continue
        echo "$d control=$(cat "$d/power/control") autosuspend=$(cat "$d/power/autosuspend")"
    done
    echo "usbfs_memory_mb=$(cat /sys/module/usbcore/parameters/usbfs_memory_mb 2>/dev/null)"
    echo "-- kernel --"
    journalctl -k --no-pager 2>/dev/null | grep -iE "uvc|realsense|2-2.3" | tail -6
}

# ---------- 入口 ----------
case "${1:-}" in
    status)  status ;;
    restore) restore ;;
    view)    view ;;
    persist) check_occupation; find_cam; apply_power; verify; persist ;;
    *)       check_occupation; find_cam; apply_power; verify
             echo
             echo "完成。下一步:"
             echo "  只读状态  : bash $0 status"
             echo "  看实时画面: bash $0 view"
             echo "  永久生效  : bash $0 persist"
             echo "  还原出厂  : bash $0 restore"
             ;;
esac
