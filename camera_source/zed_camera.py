import asyncio
import numpy as np
import pyzed.sl as sl
import cv2
import logging

logger = logging.getLogger("camera")


class ZedCamera:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ZedCamera, cls).__new__(cls)
            cls._instance._zed = None
            cls._instance._opened = False
            cls._instance.mat_left = sl.Mat()
            cls._instance.mat_right = sl.Mat()
            cls._instance.runtime_parameters = sl.RuntimeParameters()
            cls._instance._width = 1920
            cls._instance._height = 1080
        return cls._instance

    async def open(self):
        async with self._lock:
            if self._opened:
                return True

            self._zed = sl.Camera()
            init_params = sl.InitParameters()
            init_params.camera_resolution = sl.RESOLUTION.HD1080
            init_params.camera_fps = 30
            init_params.depth_mode = sl.DEPTH_MODE.NONE

            err = self._zed.open(init_params)
            if err != sl.ERROR_CODE.SUCCESS:
                logger.error(f"ZED Open Error: {err}")
                return False

            # 读取实际输出格式
            camera_info = self._zed.get_camera_information()
            actual_resolution = camera_info.camera_configuration.resolution
            actual_fps = camera_info.camera_configuration.fps
            serial_number = camera_info.serial_number
            camera_model = camera_info.camera_model

            self._width = actual_resolution.width
            self._height = actual_resolution.height

            self._opened = True
            logger.info("ZED Camera opened")
            logger.info(f"ZED Camera model: {camera_model}, SN: {serial_number}")
            logger.info(
                f"ZED Camera format: {self._width}x{self._height} @ {actual_fps} fps"
            )
            logger.info(
                f"ZED Camera YUV output: Side-by-Side format ({self._width*2}x{self._height})"
            )
            return True

    async def get_frame(self):
        """
        获取 Side-by-Side (SBS) YUV NV12 格式的帧
        返回字典: {"y": y_plane, "uv": uv_plane, "width": int, "height": int, "format": "nv12"}
        """
        if not self._opened:
            if not await self.open():
                return None

        # 使用锁确保 grab() 不会被并发调用
        async with self._lock:
            err = self._zed.grab(self.runtime_parameters)
            if err == sl.ERROR_CODE.SUCCESS:
                self._zed.retrieve_image(self.mat_left, sl.VIEW.LEFT)
                self._zed.retrieve_image(self.mat_right, sl.VIEW.RIGHT)

                img_left = self.mat_left.get_data()
                img_right = self.mat_right.get_data()

                # 去掉 alpha 通道，转换为 BGR
                img_left_bgr = img_left[:, :, :3]
                img_right_bgr = img_right[:, :, :3]

                # 拼接 SBS 格式
                frame_sbs = np.hstack((img_left_bgr, img_right_bgr))

                # 转换为 YUV NV12 格式
                yuv = cv2.cvtColor(frame_sbs, cv2.COLOR_BGR2YUV_I420)
                h, w = frame_sbs.shape[:2]

                # I420 格式: Y 平面 + U 平面 + V 平面
                y_plane = yuv[:h, :].copy()
                u_plane = yuv[h : h + h // 4, :].reshape(h // 2, w // 2)
                v_plane = yuv[h + h // 4 :, :].reshape(h // 2, w // 2)

                # 转换为 NV12 (交错 UV)
                uv_plane = np.empty((h // 2, w), dtype=np.uint8)
                uv_plane[:, 0::2] = u_plane
                uv_plane[:, 1::2] = v_plane

                return {
                    "y": y_plane,
                    "uv": uv_plane,
                    "width": w,
                    "height": h,
                    "format": "nv12",
                }
            else:
                return None

    def close(self):
        if self._opened and self._zed:
            self._zed.close()
            self._opened = False
            logger.info("ZED Camera closed")


camera_instance = ZedCamera()
