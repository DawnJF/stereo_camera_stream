import asyncio
import numpy as np
import pyzed.sl as sl
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
        return cls._instance

    async def open(self):
        async with self._lock:
            if self._opened:
                return True
            
            self._zed = sl.Camera()
            init_params = sl.InitParameters()
            init_params.camera_resolution = sl.RESOLUTION.HD720
            init_params.camera_fps = 30
            init_params.depth_mode = sl.DEPTH_MODE.NONE

            err = self._zed.open(init_params)
            if err != sl.ERROR_CODE.SUCCESS:
                logger.error(f"ZED Open Error: {err}")
                return False
            
            self._opened = True
            logger.info("ZED Camera opened")
            return True

    async def get_frame_sbs(self):
        """
        获取 Side-by-Side (SBS) 格式的帧
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

                # 拼接 SBS 格式 (去掉 alpha 通道)
                frame_sbs = np.hstack((img_left[:, :, :3], img_right[:, :, :3]))
                return frame_sbs
            else:
                return None

    def close(self):
        if self._opened and self._zed:
            self._zed.close()
            self._opened = False
            logger.info("ZED Camera closed")

camera_instance = ZedCamera()
