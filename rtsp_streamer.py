import asyncio
import subprocess
import cv2
import numpy as np
from camera_source.agent import camera
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rtsp_streamer")


def detect_hardware_encoder():
    """检测 ffmpeg 是否支持常见的硬件 H.264 编码器，有则返回编码器名称，否则返回 None。"""
    # 按优先级排列的候选列表（覆盖常见 NVIDIA / Intel / VAAPI / V4L2 场景）
    candidates = [
        "h264_nvenc",  # NVIDIA GPU（桌面卡/部分 Jetson，ffmpeg 启用 nvenc 时）
        "hevc_nvenc",
        "h264_qsv",  # Intel Quick Sync
        "hevc_qsv",
        "h264_vaapi",  # VAAPI（部分集显 / AMD）
        "hevc_vaapi",
        "h264_v4l2m2m",  # Raspberry Pi / V4L2 M2M
        "hevc_v4l2m2m",
        "h264_nvmpi",  # 部分 Jetson 上定制 ffmpeg 的旧接口
    ]

    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        logger.warning("ffmpeg not found when detecting encoders, fallback to libx264")
        return None

    output = result.stdout or result.stderr or ""

    # 简单字符串匹配：行里包含空格+编码器名+空格 即认为存在
    for enc in candidates:
        if f" {enc} " in output:
            logger.info(f"Detected hardware encoder: {enc}")
            return enc

    logger.info("No known hardware encoder detected, will use software libx264")
    return None


async def start_rtsp_stream(host, port, path):
    """
    向外部 RTSP 服务器推流（例如 mediamtx）
    - 本脚本负责采集 ZED 画面并通过 ffmpeg 编码后推到 rtsp://host:port/path
    - 实际的 RTSP 监听和客户端连接由外部服务器（如 mediamtx）完成
    """
    # 等待摄像头打开
    if not await camera.open():
        logger.error("Failed to open ZED camera")
        return

    # 获取第一帧以确定分辨率
    frame = await camera.get_frame()
    if frame is None:
        logger.error("Failed to get initial frame")
        return

    height, width = frame.shape[:2]
    fps = 30
    rtsp_url = f"rtsp://{host}:{port}/{path}"

    # 检测可用的硬件编码器，如果没有则回退到 libx264
    video_encoder = detect_hardware_encoder() or "libx264"

    # 不同编码器使用不同的编码参数
    encoder_options = []
    if video_encoder == "libx264":
        # libx264 支持 ultrafast / zerolatency
        encoder_options = [
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
        ]
    elif "nvenc" in video_encoder:
        # NVENC 不支持 ultrafast / zerolatency 这样的 x264 预设
        # 使用 NVENC 支持的预设（p1 为低延迟、最快）
        encoder_options = [
            "-preset",
            "p1",
        ]

    # ffmpeg 推流命令
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-c:v",
        video_encoder,
        "-pix_fmt",
        "yuv420p",
        *encoder_options,
        # 通过 RTSP 推流到外部服务器（如 mediamtx）
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        "-muxdelay",
        "0.01",
        rtsp_url,
    ]

    logger.info(f"Streaming to external RTSP server at: {rtsp_url}")
    logger.info(
        "请确保 RTSP 服务器 (例如 mediamtx) 已在该地址监听，然后用 VLC/ffplay 打开同样的 URL。"
    )

    try:
        # 在 listen 模式下，ffmpeg 会在此阻塞直到有客户端连接
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
    except FileNotFoundError:
        logger.error("ffmpeg not found. Please install ffmpeg: sudo apt install ffmpeg")
        return

    try:
        while True:
            frame = await camera.get_frame()
            if frame is not None:
                try:
                    process.stdin.write(frame.tobytes())
                except (BrokenPipeError, IOError):
                    logger.info("RTSP server disconnected or streaming pipe closed.")
                    break
            else:
                await asyncio.sleep(0.01)
    except Exception as e:
        logger.error(f"Streaming error: {e}")
    finally:
        if process.stdin:
            process.stdin.close()
        process.terminate()
        process.wait()
        camera.close()


"""
1.
cd /home/mjf/code/media_server
./mediamtx

2.
运行本脚本，推流到本地 mediamtx 服务器

3.
ffplay -rtsp_transport tcp rtsp://127.0.0.1:8554/stream
ffplay -fflags nobuffer -flags low_delay -framedrop -rtsp_transport udp rtsp://127.0.0.1:8554/stream
"""

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ZED RTSP Server (Listen Mode)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to listen on")
    parser.add_argument("--port", type=str, default="8554", help="Port to listen on")
    parser.add_argument("--path", type=str, default="stream", help="RTSP path")
    args = parser.parse_args()

    try:
        asyncio.run(start_rtsp_stream(args.host, args.port, args.path))
    except KeyboardInterrupt:
        pass
