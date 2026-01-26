import asyncio
import logging
import numpy as np
from aiortc import VideoStreamTrack
from av import VideoFrame
from camera_source.agent import camera


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
