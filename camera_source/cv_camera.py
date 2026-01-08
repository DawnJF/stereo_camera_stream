import asyncio
import numpy as np
from objc import NULL
from Foundation import NSObject
from AVFoundation import (
    AVCaptureDevice,
    AVCaptureDeviceInput,
    AVCaptureSession,
    AVCaptureVideoDataOutput,
    AVMediaTypeVideo,
    AVCaptureSessionPreset1920x1080,
)
from Quartz import (
    CVPixelBufferGetWidth,
    CVPixelBufferGetHeight,
    CVPixelBufferLockBaseAddress,
    CVPixelBufferUnlockBaseAddress,
    CVPixelBufferGetBaseAddressOfPlane,
    CVPixelBufferGetBytesPerRowOfPlane,
    kCVPixelBufferLock_ReadOnly,
    kCVPixelBufferPixelFormatTypeKey,
    kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
)
import CoreMedia


class FrameDelegate(NSObject):
    """AVCaptureVideoDataOutputSampleBufferDelegate"""

    def init(self):
        from objc import super as objc_super

        self = objc_super(FrameDelegate, self).init()
        if self is None:
            return None
        self.latest_frame = None
        self.frame_lock = asyncio.Lock()
        return self

    def captureOutput_didOutputSampleBuffer_fromConnection_(
        self, output, sample_buffer, connection
    ):
        """当有新的视频帧可用时被调用"""
        image_buffer = CoreMedia.CMSampleBufferGetImageBuffer(sample_buffer)
        if image_buffer is None:
            return

        # 锁定像素缓冲区
        CVPixelBufferLockBaseAddress(image_buffer, kCVPixelBufferLock_ReadOnly)

        width = CVPixelBufferGetWidth(image_buffer)
        height = CVPixelBufferGetHeight(image_buffer)

        # 获取 Y 平面
        y_base_address = CVPixelBufferGetBaseAddressOfPlane(image_buffer, 0)
        y_bytes_per_row = CVPixelBufferGetBytesPerRowOfPlane(image_buffer, 0)
        y_data = np.frombuffer(
            y_base_address.as_buffer(y_bytes_per_row * height), dtype=np.uint8
        ).reshape(height, y_bytes_per_row)

        # 获取 UV 平面 (NV12 格式)
        uv_base_address = CVPixelBufferGetBaseAddressOfPlane(image_buffer, 1)
        uv_bytes_per_row = CVPixelBufferGetBytesPerRowOfPlane(image_buffer, 1)
        uv_height = height // 2
        uv_data = np.frombuffer(
            uv_base_address.as_buffer(uv_bytes_per_row * uv_height), dtype=np.uint8
        ).reshape(uv_height, uv_bytes_per_row)

        # 解锁像素缓冲区
        CVPixelBufferUnlockBaseAddress(image_buffer, kCVPixelBufferLock_ReadOnly)

        # 裁剪到实际宽度（去除 padding）
        y_plane = y_data[:, :width].copy()
        uv_plane = uv_data[:, :width].copy()

        # 存储 YUV 数据 (NV12 格式)
        self.latest_frame = {
            "y": y_plane,
            "uv": uv_plane,
            "width": width,
            "height": height,
            "format": "nv12",
        }


class CVCamera:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls, device_id=0):
        if cls._instance is None:
            cls._instance = super(CVCamera, cls).__new__(cls)
            cls._instance._session = None
            cls._instance._opened = False
            cls._instance._device_id = device_id
            cls._instance._delegate = None
        return cls._instance

    async def open(self):
        async with self._lock:
            if self._opened:
                return True

            # 获取摄像头设备
            devices = AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo)
            if not devices or self._device_id >= len(devices):
                print(f"CV Camera Open Error: Cannot find device {self._device_id}")
                return False

            device = devices[self._device_id]

            # 创建输入
            device_input, error = AVCaptureDeviceInput.deviceInputWithDevice_error_(
                device, None
            )
            if error is not None:
                print(f"CV Camera Open Error: {error}")
                return False

            # 创建会话
            self._session = AVCaptureSession.alloc().init()
            self._session.setSessionPreset_(AVCaptureSessionPreset1920x1080)

            if not self._session.canAddInput_(device_input):
                print("CV Camera Open Error: Cannot add input")
                return False
            self._session.addInput_(device_input)

            # 创建输出
            video_output = AVCaptureVideoDataOutput.alloc().init()

            # 设置像素格式为 NV12 (420YpCbCr8BiPlanarFullRange)
            video_output.setVideoSettings_(
                {
                    kCVPixelBufferPixelFormatTypeKey: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange
                }
            )

            # 创建委托
            self._delegate = FrameDelegate.alloc().init()

            # 设置输出的委托和队列
            from dispatch import dispatch_queue_create, DISPATCH_QUEUE_SERIAL

            queue = dispatch_queue_create(b"videoQueue", DISPATCH_QUEUE_SERIAL)
            video_output.setSampleBufferDelegate_queue_(self._delegate, queue)

            if not self._session.canAddOutput_(video_output):
                print("CV Camera Open Error: Cannot add output")
                return False
            self._session.addOutput_(video_output)

            # 开始会话
            self._session.startRunning()

            self._opened = True
            print(
                f"CV Camera opened: device {self._device_id} ({device.localizedName()})"
            )
            print(f"CV Camera format: 1920x1080 @ 30 fps, YUV NV12")
            return True

    async def get_frame(self):
        """
        获取单个帧 (YUV NV12 格式)
        返回字典: {"y": y_plane, "uv": uv_plane, "width": int, "height": int, "format": "nv12"}
        """
        if not self._opened:
            if not await self.open():
                return None

        # 等待帧可用
        max_wait = 1.0
        wait_time = 0
        while self._delegate.latest_frame is None and wait_time < max_wait:
            await asyncio.sleep(0.01)
            wait_time += 0.01

        if self._delegate.latest_frame is None:
            print("Failed to read frame from CV camera")
            return None

        return self._delegate.latest_frame

    def close(self):
        if self._opened and self._session:
            self._session.stopRunning()
            self._opened = False
            print("CV Camera closed")


camera_instance = CVCamera()
