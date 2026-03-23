#!/usr/bin/env python3
import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")
from gi.repository import Gst, GstRtspServer, GLib

Gst.init(None)


class H265Factory(GstRtspServer.RTSPMediaFactory):
    def __init__(self):
        super().__init__()
        width = 3040
        height = 1520
        # width = 2560
        # height = 720
        self.set_launch(
            "( v4l2src device=/dev/video0 io-mode=2 do-timestamp=true ! "
            "image/jpeg,width="
            + str(width)
            + ",height="
            + str(height)
            + ",framerate=30/1 ! "
            "nvjpegdec ! "
            "nvvideoconvert ! "
            "video/x-raw(memory:Cuda),format=NV12 ! "  # 保持在显存中
            "nvh264enc bitrate=8000 preset=p1 tune=zerolatency rc-mode=cbr-ld-hq zerolatency=true gop-size=30 bframes=0 ! "
            "h264parse ! "
            "rtph264pay config-interval=1 name=pay0 pt=96 )"
        )
        self.set_launch(
            "( v4l2src device=/dev/video0 io-mode=2 do-timestamp=true ! "
            "image/jpeg,width="
            + str(width)
            + ",height="
            + str(height)
            + ",framerate=30/1 ! "
            "jpegdec ! "
            "queue max-size-time=0 max-size-bytes=0 max-size-buffers=1 leaky=downstream ! "
            "videoconvert ! video/x-raw,format=NV12 ! "
            "nvh264enc bitrate=8000 preset=low-latency rc-mode=cbr zerolatency=true gop-size=30 bframes=0 ! "
            "h264parse config-interval=1 ! "
            "rtph264pay config-interval=1 name=pay0 pt=96 )"
        )
        self.set_shared(True)


server = GstRtspServer.RTSPServer()
mounts = server.get_mount_points()
mounts.add_factory("/test", H265Factory())
server.attach(None)
GLib.MainLoop().run()


"""
ffplay -fflags nobuffer -flags low_delay -framedrop -rtsp_transport udp rtsp://192.168.2.127:8554/test
"""
