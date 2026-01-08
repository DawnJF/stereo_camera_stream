import asyncio
import cv2
import numpy as np
from camera_source.zed_camera import camera_instance

# from camera_source.v4l2_camera import camera_instance


async def _test_camera_save_frames():
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


def test_save_frames():
    asyncio.run(_test_camera_save_frames())


if __name__ == "__main__":
    test_save_frames()
