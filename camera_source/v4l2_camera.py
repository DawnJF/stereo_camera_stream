import asyncio
import cv2


class V4L2Camera:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls, device="/dev/video4"):
        if cls._instance is None:
            cls._instance = super(V4L2Camera, cls).__new__(cls)
            cls._instance._cap = None
            cls._instance._opened = False
            cls._instance._device = device
        return cls._instance

    async def open(self):
        async with self._lock:
            if self._opened:
                return True

            self._cap = cv2.VideoCapture(self._device)
            if not self._cap.isOpened():
                logger.error(f"V4L2 Camera Open Error: Cannot open {self._device}")
                return False

            # 设置摄像头参数（可选）
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            self._cap.set(cv2.CAP_PROP_FPS, 30)

            self._opened = True
            logger.info(f"V4L2 Camera opened: {self._device}")
            return True

    async def get_frame(self):
        """
        获取单个帧
        """
        if not self._opened:
            if not await self.open():
                return None

        # 使用锁确保读取不会被并发调用
        async with self._lock:
            ret, frame = self._cap.read()
            if ret:
                return frame
            else:
                logger.warning("Failed to read frame from V4L2 camera")
                return None

    def close(self):
        if self._opened and self._cap:
            self._cap.release()
            self._opened = False
            logger.info("V4L2 Camera closed")


camera_instance = V4L2Camera()
