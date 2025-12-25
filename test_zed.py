import pyzed.sl as sl
import asyncio
import cv2
import numpy as np
from server import ZedCameraTrack


def test_zed_camera():
    """
    测试 ZED 摄像头是否可以正常打开并获取基本信息。
    """
    # 创建 Camera 对象
    zed = sl.Camera()

    # 配置初始化参数
    init_params = sl.InitParameters()
    init_params.camera_resolution = sl.RESOLUTION.HD720
    init_params.camera_fps = 30
    init_params.depth_mode = sl.DEPTH_MODE.NONE  # 仅测试打开，不需要深度

    print("正在尝试打开 ZED 摄像头...")

    # 打开摄像头
    err = zed.open(init_params)
    if err != sl.ERROR_CODE.SUCCESS:
        print(f"无法打开 ZED 摄像头: {err}")
        return False

    # 获取摄像头信息
    info = zed.get_camera_information()
    print(f"成功打开 ZED 摄像头!")
    print(f"序列号: {info.serial_number}")
    print(f"型号: {info.camera_model}")
    print(
        f"分辨率: {info.camera_configuration.resolution.width}x{info.camera_configuration.resolution.height}"
    )
    print(f"FPS: {info.camera_configuration.fps}")

    # 关闭摄像头
    zed.close()
    print("摄像头已关闭。")
    return True


async def _test_zed_track_save_frames():
    """
    测试 ZedCameraTrack 类并保存前 2 帧图像。
    """
    print("正在初始化 ZedCameraTrack...")
    track = ZedCameraTrack()

    try:
        for i in range(2):
            print(f"正在获取第 {i+1} 帧...")
            # 调用 recv() 获取 VideoFrame
            frame = await track.recv()

            # 将 VideoFrame 转换为 ndarray (BGR 格式)
            # 注意：ZedCameraTrack 内部已经拼接成了 SBS 格式
            img = frame.to_ndarray(format="bgr24")

            # 保存图像
            filename = f"zed_frame_{i+1}.jpg"
            cv2.imwrite(filename, img)
            print(f"已保存: {filename} (尺寸: {img.shape[1]}x{img.shape[0]})")

    except Exception as e:
        print(f"测试过程中出现错误: {e}")
    finally:
        print("正在关闭轨道...")
        track.stop()


def test_zed_track_save_frames():
    asyncio.run(_test_zed_track_save_frames())


if __name__ == "__main__":
    # test_zed_camera()
    test_zed_track_save_frames()
