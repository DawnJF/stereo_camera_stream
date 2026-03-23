gst-inspect-1.0


## Jetson

验证硬件链路正常

```
gst-launch-1.0 \
v4l2src device=/dev/video0 io-mode=2 ! \
image/jpeg,width=2560,height=1440,framerate=30/1 ! \
nvv4l2decoder mjpeg=1 ! \
nvv4l2h265enc maxperf-enable=1 iframeinterval=30 insert-sps-pps=1 bitrate=8000000 ! \
h265parse ! \
fakesink
```

如果能跑：CPU 占用很低 & 没有掉帧 &不报错

说明：
✅ MJPG 硬解正常
✅ H.265 硬编正常
✅ 零拷贝链路 OK


```
sudo apt install libgstrtspserver-1.0-0 gstreamer1.0-rtsp

gst-rtsp-launch ( \
v4l2src device=/dev/video0 io-mode=2 ! \
image/jpeg,width=2560,height=1440,framerate=30/1 ! \
nvv4l2decoder mjpeg=1 ! \
nvv4l2h265enc maxperf-enable=1 iframeinterval=30 insert-sps-pps=1 bitrate=8000000 ! \
h265parse ! rtph265pay name=pay0 pt=96 \
)


rtsp://你的IP:8554/test
```



## PC


测试
```
gst-launch-1.0 \
v4l2src device=/dev/video0 io-mode=2 ! \
image/jpeg,width=3040,height=1520,framerate=30/1 ! \
jpegdec ! \
videoconvert ! \
nvh265enc bitrate=8000 preset=low-latency-hq ! \
h265parse ! \
fakesink
```

mediamtx.yml
```
paths:
  test:
    source: udp://127.0.0.1:5004
```

```
gst-launch-1.0 -v \
v4l2src device=/dev/video0 io-mode=2 ! \
image/jpeg,width=3040,height=1520,framerate=30/1 ! \
jpegdec ! videoconvert ! video/x-raw,format=NV12 ! \
nvh265enc bitrate=8000 preset=low-latency-hq rc-mode=cbr zerolatency=true gop-size=30 ! \
h265parse config-interval=1 ! \
mpegtsmux ! \
udpsink host=127.0.0.1 port=5004
```


gst-launch-1.0 -v \
v4l2src device=/dev/video0 io-mode=2 ! \
image/jpeg,width=3040,height=1520,framerate=30/1 ! \
jpegdec ! videoconvert ! video/x-raw,format=NV12 ! \
nvh265enc bitrate=8000 preset=low-latency-hq rc-mode=cbr zerolatency=true gop-size=30 ! \
h265parse config-interval=1 ! rtph265pay mtu=1400 ! \
udpsink host=127.0.0.1 port=5004



test ok
gst-launch-1.0 -v v4l2src device=/dev/video0 io-mode=2 do-timestamp=true ! \
image/jpeg,width=3040,height=1520,framerate=30/1 ! \
nvjpegdec ! \
nvvideoconvert ! \
"video/x-raw,format=NV12" ! \
nvh264enc bitrate=8000 preset=1 rc-mode=cbr-ld-hq gop-size=30 bframes=0 ! \
h264parse ! \
rtph264pay config-interval=1 name=pay0 pt=96 ! \
udpsink host=127.0.0.1 port=5000 sync=false