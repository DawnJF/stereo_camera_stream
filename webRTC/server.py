import argparse
import asyncio
import json
import logging
import os
import sys
import cv2
import numpy as np
import ssl
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame

sys.path.append(os.getcwd())
from camera_source.agent import camera


# --- Camera 摄像头处理类 ---
class CameraTrack(VideoStreamTrack):
    """
    自定义 WebRTC 视频轨道，源数据来自摄像头，优先处理 YUV 格式
    """

    def __init__(self):
        super().__init__()

    async def recv(self):
        """
        WebRTC 会不断调用这个方法获取下一帧
        优先处理 YUV NV12 格式以提高性能
        """
        try:
            frame = await camera.get_frame()
            if frame is None:
                await asyncio.sleep(0.01)
                return await self.recv()

            # 统计并打印帧率信息
            if not hasattr(self, "_frame_count"):
                self._frame_count = 0
            self._frame_count += 1

            pts, time_base = await self.next_timestamp()

            # 检查是否是 YUV 字典格式
            if isinstance(frame, dict) and frame.get("format") == "nv12":
                # 处理 YUV NV12 格式
                y_plane = frame["y"]
                uv_plane = frame["uv"]
                width = frame["width"]
                height = frame["height"]

                if self._frame_count % 300 == 0:
                    logging.info(
                        f"Successfully sent 300 YUV frames to WebRTC. Size: {width}x{height}"
                    )

                # 从 NV12 平面创建 VideoFrame
                # aiortc 的 VideoFrame.from_ndarray 需要完整的 YUV420p 格式
                # NV12 需要转换为 I420 (planar YUV)

                # 分离 UV 平面
                # 注意：切片会生成 strided view（非 C-contiguous），PyAV 不接受。
                y_plane = np.ascontiguousarray(y_plane)
                u_plane = np.ascontiguousarray(uv_plane[:, 0:width:2])
                v_plane = np.ascontiguousarray(uv_plane[:, 1:width:2])

                # 使用 av 库直接创建 yuv420p VideoFrame
                new_frame = VideoFrame(width=width, height=height, format="yuv420p")

                # 填充数据
                new_frame.planes[0].update(y_plane)
                new_frame.planes[1].update(u_plane)
                new_frame.planes[2].update(v_plane)

                new_frame.pts = pts
                new_frame.time_base = time_base

                return new_frame
            else:
                # 处理传统 BGR/RGB numpy 数组格式
                if self._frame_count % 100 == 0:
                    logging.info(
                        f"Successfully sent 100 BGR frames to WebRTC. Shape: {frame.shape}"
                    )

                # 从 BGR numpy 数组创建 VideoFrame
                frame = np.ascontiguousarray(frame)
                new_frame = VideoFrame.from_ndarray(frame, format="bgr24")
                new_frame.pts = pts
                new_frame.time_base = time_base

                # 转换为 yuv420p 提高 WebRTC 兼容性
                new_frame = new_frame.reformat(format="yuv420p")
                return new_frame

        except Exception as e:
            logging.error(f"Error in CameraTrack.recv: {e}")
            raise e

    def stop(self):
        # 注意：这里不直接关闭全局 camera 实例，因为可能有其他轨道在使用
        # 可以在 app shutdown 时统一关闭
        super().stop()


# --- Web 服务器与信令处理 ---

ROOT = os.path.dirname(__file__)


async def index(request):
    with open(os.path.join(ROOT, "index.html"), "r", encoding="utf-8") as f:
        content = f.read()
    return web.Response(content_type="text/html", text=content)


async def babylon(request):
    with open(os.path.join(ROOT, "babylon_xr.html"), "r", encoding="utf-8") as f:
        content = f.read()
    return web.Response(content_type="text/html", text=content)


async def seethrough(request):
    with open(os.path.join(ROOT, "seethrough.html"), "r", encoding="utf-8") as f:
        content = f.read()
    return web.Response(content_type="text/html", text=content)


async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs.add(pc)

    # 添加摄像头视频轨道
    # 这里我们每次请求都创建一个新的 Track 实例，实际可能会共享同一个摄像头实例
    # 注意：某些 SDK（如 ZED）不允许多个进程同时由同一个对象打开，
    # 如果要多客户端观看，需要设计一个单例模式的帧获取器
    camera_track = CameraTrack()
    pc.addTrack(camera_track)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state is {pc.connectionState}")
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)
            camera_track.stop()
        elif pc.connectionState == "closed":
            camera_track.stop()

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        print(f"ICE connection state is {pc.iceConnectionState}")

    @pc.on("track")
    def on_track(track):
        print(f"Track {track.kind} received")

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    # 打印本地生成的候选地址，方便调试
    # for candidate in pc.localDescription.sdp.split('\n'):
    #     if 'a=candidate' in candidate:
    #         print(f"Local Candidate: {candidate.strip()}")

    # 等待 ICE 收集完成
    timeout = 5
    start_time = asyncio.get_event_loop().time()
    while pc.iceGatheringState != "complete":
        if asyncio.get_event_loop().time() - start_time > timeout:
            print("ICE gathering timed out")
            break
        await asyncio.sleep(0.1)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        ),
    )


pcs = set()


async def on_shutdown(app):
    # 关闭所有连接
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

    # 关闭 ZED 相机
    camera.close()


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="WebRTC Camera Streamer")
    parser.add_argument(
        "--cert-file",
        default="webRTC/cert.pem",
        help="SSL certificate file (for HTTPS)",
    )
    parser.add_argument(
        "--key-file", default="webRTC/key.pem", help="SSL key file (for HTTPS)"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host for HTTP server")
    parser.add_argument("--port", type=int, default=8080, help="Port for HTTP server")
    args = parser.parse_args()

    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_get("/video", babylon)
    app.router.add_get("/ar", seethrough)
    app.router.add_post("/offer", offer)

    if args.cert_file and args.key_file:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(args.cert_file, args.key_file)
    else:
        ssl_context = None
        print("Warning: Running without HTTPS. WebXR will only work on localhost.")

    if ssl_context:
        print(f"Server started at https://{args.host}:{args.port}")
    else:
        print(f"Server started at http://{args.host}:{args.port}")

    web.run_app(app, host=args.host, port=args.port, ssl_context=ssl_context)


"""

openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

python webRTC/server.py

https://0.0.0.0:8080/ar?useStun=false


"""
