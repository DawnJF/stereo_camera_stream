import asyncio
import cv2
import logging
import numpy as np

logger = logging.getLogger("camera")


class V4L2Camera:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls, device="/dev/video0"):
        if cls._instance is None:
            cls._instance = super(V4L2Camera, cls).__new__(cls)
            cls._instance._cap = None
            cls._instance._opened = False
            cls._instance._device = device
            cls._instance._use_yuv = False
            cls._instance._width = 320
            cls._instance._height = 240
        return cls._instance

    async def open(self):
        async with self._lock:
            if self._opened:
                return True

            # 尝试使用 V4L2 直接读取 YUV
            try:
                self._cap = cv2.VideoCapture(self._device, cv2.CAP_V4L2)
                if self._cap.isOpened():
                    # 尝试设置 YUV422 或 YUYV 格式
                    self._cap.set(
                        cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc("Y", "U", "Y", "V")
                    )
                    self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
                    self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
                    self._cap.set(cv2.CAP_PROP_FPS, 60)

                    # 检查是否成功设置为 YUV
                    fourcc = int(self._cap.get(cv2.CAP_PROP_FOURCC))
                    fourcc_str = "".join(
                        [chr((fourcc >> 8 * i) & 0xFF) for i in range(4)]
                    )

                    if fourcc_str in ["YUYV", "YUY2", "UYVY"]:
                        self._use_yuv = True
                        logger.info(
                            f"V4L2 Camera using native YUV format: {fourcc_str}"
                        )
                    else:
                        logger.info(f"V4L2 Camera fallback to BGR format: {fourcc_str}")
                        self._use_yuv = False
            except Exception as e:
                logger.warning(
                    f"Failed to open V4L2 with YUV, fallback to default: {e}"
                )
                self._cap = cv2.VideoCapture(self._device)
                self._use_yuv = False

            if not self._cap.isOpened():
                logger.error(f"V4L2 Camera Open Error: Cannot open {self._device}")
                return False

            # 读取实际输出格式
            actual_width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fps = self._cap.get(cv2.CAP_PROP_FPS)

            self._width = actual_width
            self._height = actual_height
            self._opened = True
            logger.info(f"V4L2 Camera opened: {self._device}")
            logger.info(
                f"V4L2 Camera format: {actual_width}x{actual_height} @ {actual_fps:.2f} fps"
            )
            return True

    async def get_frame(self):
        """
        获取单个帧，优先返回 YUV 格式
        如果是 YUV 格式，返回字典: {"y": y_plane, "uv": uv_plane, "width": int, "height": int, "format": "nv12"}
        否则返回 BGR numpy array
        """
        if not self._opened:
            if not await self.open():
                return None

        # 使用锁确保读取不会被并发调用
        async with self._lock:
            ret, frame = self._cap.read()
            if not ret:
                logger.warning("Failed to read frame from V4L2 camera")
                return None

            if self._use_yuv and len(frame.shape) == 2:
                # YUYV 格式转换为 NV12
                # YUYV: Y0 U0 Y1 V0 (4 bytes for 2 pixels)
                h, w = frame.shape
                if w == self._width * 2:  # YUYV packed format
                    # 提取 Y 通道
                    y_plane = frame[:, 0::2].copy()

                    # 提取并下采样 U V 通道生成 NV12 格式
                    u = frame[::2, 1::4]
                    v = frame[::2, 3::4]
                    uv_plane = np.empty(
                        (self._height // 2, self._width), dtype=np.uint8
                    )
                    uv_plane[:, 0::2] = u
                    uv_plane[:, 1::2] = v

                    return {
                        "y": y_plane,
                        "uv": uv_plane,
                        "width": self._width,
                        "height": self._height,
                        "format": "nv12",
                    }

            # 如果不是 YUV，将 BGR 转换为 YUV NV12
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)
                h, w = frame.shape[:2]

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

            return frame

    def close(self):
        if self._opened and self._cap:
            self._cap.release()
            self._opened = False
            logger.info("V4L2 Camera closed")


camera_instance = V4L2Camera()
