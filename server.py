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

    def __init__(self):
        super().__init__()  # 初始化父类

        # 初始化 ZED 相机
        self.zed = sl.Camera()
        self.init_params = sl.InitParameters()
        self.init_params.camera_resolution = (
            sl.RESOLUTION.HD720
        )  # 720p 比较流畅，VR可尝试 HD1080
        self.init_params.camera_fps = 30
        self.init_params.depth_mode = (
            sl.DEPTH_MODE.NONE
        )  # 直播视频不需要深度计算，节省性能

        err = self.zed.open(self.init_params)
        if err != sl.ERROR_CODE.SUCCESS:
            print(f"ZED Open Error: {err}")
            exit(1)

        self.runtime_parameters = sl.RuntimeParameters()
        self.mat_left = sl.Mat()
        self.mat_right = sl.Mat()

    async def recv(self):
        """
        WebRTC 会不断调用这个方法获取下一帧
        """
        pts, time_base = await self.next_timestamp()

        # ZED SDK 取图是阻塞的，但在 aiortc 中最好不要阻塞太久
        # 实际生产中可能需要放在单独的线程，这里为了简化直接调用
        err = self.zed.grab(self.runtime_parameters)

        if err == sl.ERROR_CODE.SUCCESS:
            # 1. 获取左右眼图像
            self.zed.retrieve_image(self.mat_left, sl.VIEW.LEFT)
            self.zed.retrieve_image(self.mat_right, sl.VIEW.RIGHT)

            # 2. 转换为 Numpy 数组 (BGRA)
            img_left = self.mat_left.get_data()
            img_right = self.mat_right.get_data()

            # 3. 去掉 Alpha 通道 (BGRA -> BGR) 并拼接
            # VR 通常使用 Side-by-Side (SBS) 格式：左眼在左，右眼在右
            # 只取前三个通道 [:,:,:3]
            frame_sbs = np.hstack((img_left[:, :, :3], img_right[:, :, :3]))

            # 可选：缩放以降低带宽压力 (例如缩放到 1920x540 总大小)
            # frame_sbs = cv2.resize(frame_sbs, (1920, 540))

            # 4. 构建 PyAV VideoFrame 给 WebRTC
            # ZED 默认是 BGR 格式，av.VideoFrame 需要指明格式
            new_frame = VideoFrame.from_ndarray(frame_sbs, format="bgr24")
            new_frame.pts = pts
            new_frame.time_base = time_base
            return new_frame
        else:
            # 如果抓取失败，返回空或者是黑帧，这里简单抛出等待下一帧
            # 实际需处理断连逻辑
            await asyncio.sleep(0.01)
            return await self.recv()

    def stop(self):
        self.zed.close()


# --- Web 服务器与信令处理 ---

ROOT = os.path.dirname(__file__)


async def index(request):
    content = open(os.path.join(ROOT, "index.html"), "r").read()
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
        print("Connection state is %s" % pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)
            zed_track.stop()
        elif pc.connectionState == "closed":
            zed_track.stop()

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

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


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(level=logging.INFO)

    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_post("/offer", offer)

    print("Server started at http://localhost:8080")
    web.run_app(app, host="0.0.0.0", port=8080)
