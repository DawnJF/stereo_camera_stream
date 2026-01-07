import asyncio
import cv2
import numpy as np
from camera import camera_instance, v4l2_camera_instance


async def _test_zed_save_frames():
    """
    测试 ZedCamera 类并保存前 2 帧图像。
    """
    print("正在初始化 ZedCamera...")
    if not await camera_instance.open():
        print("无法打开摄像头")
        return

    try:
        for i in range(2):
            print(f"正在获取第 {i+1} 帧...")
            # 获取 SBS 格式的帧
            img = await camera_instance.get_frame()

            if img is not None:
                # 保存图像
                filename = f"zed_frame_{i+1}.jpg"
                cv2.imwrite(filename, img)
                print(f"已保存: {filename} (尺寸: {img.shape[1]}x{img.shape[0]})")
            else:
                print(f"获取第 {i+1} 帧失败")

    except Exception as e:
        print(f"测试过程中出现错误: {e}")
    finally:
        print("正在关闭摄像头...")
        camera_instance.close()


def test_zed_save_frames():
    asyncio.run(_test_zed_save_frames())


async def _test_v4l2_save_frames():
    """
    测试 V4L2Camera 类并保存前 2 帧图像。
    """
    print("正在初始化 V4L2Camera...")
    if not await v4l2_camera_instance.open():
        print("无法打开摄像头")
        return

    try:
        for i in range(2):
            print(f"正在获取第 {i+1} 帧...")
            # 获取帧
            img = await v4l2_camera_instance.get_frame()

            if img is not None:
                # 保存图像
                filename = f"v4l2_frame_{i+1}.jpg"
                cv2.imwrite(filename, img)
                print(f"已保存: {filename} (尺寸: {img.shape[1]}x{img.shape[0]})")
            else:
                print(f"获取第 {i+1} 帧失败")

    except Exception as e:
        print(f"测试过程中出现错误: {e}")
    finally:
        print("正在关闭摄像头...")
        v4l2_camera_instance.close()


def test_v4l2_save_frames():
    asyncio.run(_test_v4l2_save_frames())


if __name__ == "__main__":
    # test_zed_save_frames()
    test_v4l2_save_frames()
