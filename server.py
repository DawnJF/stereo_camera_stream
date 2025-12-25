import argparse
import asyncio
import json
import logging
import os
import cv2
import numpy as np
import pyzed.sl as sl
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame


# --- ZED 摄像头处理类 ---
class ZedCameraTrack(VideoStreamTrack):
    """
    自定义 WebRTC 视频轨道，源数据来自 ZED 双目摄像头。
    输出格式为 Side-by-Side (SBS) 视频，适合 VR 显示。
    """

    _zed = None
    _lock = None  # 延迟初始化锁

    def __init__(self):
        super().__init__()
        self.mat_left = sl.Mat()
        self.mat_right = sl.Mat()
        self.runtime_parameters = sl.RuntimeParameters()

    @classmethod
    async def get_lock(cls):
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    async def _ensure_zed_opened(self):
        lock = await self.get_lock()
        async with lock:
            if ZedCameraTrack._zed is None:
                zed = sl.Camera()
                init_params = sl.InitParameters()
                init_params.camera_resolution = sl.RESOLUTION.HD720
                init_params.camera_fps = 30
                init_params.depth_mode = sl.DEPTH_MODE.NONE

                err = zed.open(init_params)
                if err != sl.ERROR_CODE.SUCCESS:
                    print(f"ZED Open Error: {err}")
                    return False
                ZedCameraTrack._zed = zed
                print("ZED Camera opened")
            return True

    async def recv(self):
        """
        WebRTC 会不断调用这个方法获取下一帧
        """
        try:
            if not await self._ensure_zed_opened():
                await asyncio.sleep(1)
                return await self.recv()

            pts, time_base = await self.next_timestamp()

            # 使用锁确保 grab() 不会被并发调用
            lock = await self.get_lock()
            async with lock:
                err = ZedCameraTrack._zed.grab(self.runtime_parameters)
                if err == sl.ERROR_CODE.SUCCESS:
                    ZedCameraTrack._zed.retrieve_image(self.mat_left, sl.VIEW.LEFT)
                    ZedCameraTrack._zed.retrieve_image(self.mat_right, sl.VIEW.RIGHT)

                    img_left = self.mat_left.get_data()
                    img_right = self.mat_right.get_data()

                    # 拼接 SBS 格式
                    frame_sbs = np.hstack((img_left[:, :, :3], img_right[:, :, :3]))

                    new_frame = VideoFrame.from_ndarray(frame_sbs, format="bgr24")
                    new_frame.pts = pts
                    new_frame.time_base = time_base
                    return new_frame
                else:
                    # print(f"ZED Grab Error: {err}")
                    await asyncio.sleep(0.01)
                    return await self.recv()
        except Exception as e:
            print(f"Error in ZedCameraTrack.recv: {e}")
            raise e

    def stop(self):
        # 注意：这里不直接关闭全局 zed 实例，因为可能有其他轨道在使用
        # 可以在 app shutdown 时统一关闭
        super().stop()


# --- Web 服务器与信令处理 ---

ROOT = os.path.dirname(__file__)


async def index(request):
    with open(os.path.join(ROOT, "index.html"), "r", encoding="utf-8") as f:
        content = f.read()
    return web.Response(content_type="text/html", text=content)


async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs.add(pc)

    # 添加 ZED 视频轨道
    # 这里我们每次请求都创建一个新的 Track 实例，实际可能会共享同一个 ZED 实例
    # 注意：ZED SDK 不允许多个进程同时由同一个对象打开，
    # 如果要多客户端观看，需要设计一个单例模式的 ZED Grabber
    zed_track = ZedCameraTrack()
    pc.addTrack(zed_track)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state is {pc.connectionState}")
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)
            zed_track.stop()
        elif pc.connectionState == "closed":
            zed_track.stop()

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
    if ZedCameraTrack._zed is not None:
        ZedCameraTrack._zed.close()
        ZedCameraTrack._zed = None
        print("ZED Camera closed on shutdown")


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(level=logging.INFO)

    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_post("/offer", offer)

    print("Server started at http://localhost:8080")
    web.run_app(app, host="0.0.0.0", port=8080)
