# 在Orin上跑通 3840*1080 60FPS MJPG

## 环境
gst-inspect-1.0 nvjpegdec
gst-inspect-1.0 nvv4l2h264enc
gst-inspect-1.0 jpegparse
gst-inspect-1.0 rtspclientsink
gst-inspect-1.0 nvv4l2decoder

sudo apt install gstreamer1.0-rtsp




export LD_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu/tegra:$LD_LIBRARY_PATH



dns 有问题 

sudo systemctl start systemd-resolved



maybe

强制开启最高性能模式
sudo nvpmodel -m 0
锁定 CPU/GPU/EMC 频率到最高
sudo jetson_clocks






## 推流命令

ok


gst-launch-1.0 -e \
v4l2src device=/dev/video0 io-mode=2 ! \
'image/jpeg,width=3840,height=1080,framerate=60/1' ! \
nvv4l2decoder mjpeg=1 ! \
nvvidconv ! \
'video/x-raw(memory:NVMM),format=NV12' ! \
nvv4l2h264enc \
    bitrate=6000000 \
    control-rate=1 \
    iframeinterval=60 \
    preset-level=1 \
    maxperf-enable=1 \
    insert-sps-pps=true ! \
h264parse ! \
queue max-size-buffers=1 \
rtspclientsink location=rtsp://127.0.0.1:8554/test sync=false async=false






ok too

gst-launch-1.0 -e \
v4l2src device=/dev/video0 io-mode=2 do-timestamp=true num-buffers=-1 ! \
image/jpeg,width=3840,height=1080,framerate=60/1 ! \
jpegparse ! \
nvv4l2decoder mjpeg=1 enable-max-performance=1 num-extra-surfaces=0 ! \
nvvidconv ! \
'video/x-raw(memory:NVMM),format=NV12' ! \
nvv4l2h264enc \
    bitrate=8000000 \
    control-rate=1 \
    iframeinterval=60 \
    preset-level=1 \
    maxperf-enable=1 \
    insert-sps-pps=true ! \
h264parse ! \
queue leaky=2 max-size-buffers=1 ! \
rtspclientsink location=rtsp://127.0.0.1:8554/test sync=false async=false





bad ok：

gst-launch-1.0 -e \
v4l2src device=/dev/video0 io-mode=2 ! \
image/jpeg,width=3840,height=1080,framerate=30/1 ! \
jpegparse ! \
jpegdec ! \
nvvidconv ! \
'video/x-raw(memory:NVMM),format=NV12' ! \
nvv4l2h264enc \
    bitrate=6000000 \
    control-rate=1 \
    iframeinterval=15 \
    insert-sps-pps=true \
    preset-level=1 \
    zerolatency=true \
    maxperf-enable=1 ! \
h264parse config-interval=1 ! \
rtspclientsink location=rtsp://127.0.0.1:8554/test

