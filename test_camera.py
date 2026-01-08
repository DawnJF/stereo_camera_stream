import asyncio
import cv2
import numpy as np

from camera_source.agent import camera


async def _test_camera_save_frames():
    """
    测试摄像头类并保存前 2 帧图像。
    """
    print("正在初始化摄像头...")
    if not await camera.open():
        print("无法打开摄像头")
        return

    try:
        for i in range(2):
            print(f"正在获取第 {i+1} 帧...")
            # 获取帧（可能是 YUV 字典格式或 BGR 数组）
            frame = await camera.get_frame()

            if frame is not None:
                # 检查是否是 YUV 字典格式
                if isinstance(frame, dict) and frame.get("format") == "nv12":
                    # YUV NV12 格式，需要转换为 BGR 才能保存为 JPEG
                    y_plane = frame["y"]
                    uv_plane = frame["uv"]
                    width = frame["width"]
                    height = frame["height"]

                    print(f"YUV NV12 格式: {width}x{height}")

                    # 分离 UV 平面
                    u_plane = uv_plane[:, 0::2]
                    v_plane = uv_plane[:, 1::2]

                    # 转换为 I420 (YUV420p)
                    yuv_i420 = np.concatenate(
                        [y_plane.flatten(), u_plane.flatten(), v_plane.flatten()]
                    ).reshape((height * 3 // 2, width))

                    # 转换为 BGR
                    img = cv2.cvtColor(yuv_i420, cv2.COLOR_YUV2BGR_I420)
                else:
                    # 已经是 BGR 数组格式
                    img = frame

                # 保存图像
                filename = f"camera_frame_{i+1}.jpg"
                cv2.imwrite(filename, img)
                print(f"已保存: {filename} (尺寸: {img.shape[1]}x{img.shape[0]})")
            else:
                print(f"获取第 {i+1} 帧失败")

    except Exception as e:
        print(f"测试过程中出现错误: {e}")
        import traceback

        traceback.print_exc()
    finally:
        print("正在关闭摄像头...")
        camera.close()


def test_save_frames():
    asyncio.run(_test_camera_save_frames())


if __name__ == "__main__":
    test_save_frames()
