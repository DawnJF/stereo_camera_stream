
```
sudo apt-get install python3-gi python3-gst-1.0 gstreamer1.0-plugins-bad gstreamer1.0-nice gstreamer1.0-plugins-good gstreamer1.0-plugins-base
pip3 install aiohttp
```


检查环境
gst-inspect-1.0 nice
gst-inspect-1.0 webrtcbin

测试方法 
gst-launch-1.0 v4l2src device=/dev/video0 ! video/x-raw,format=YUY2,width=640,height=480,framerate=30/1 ! videoconvert


gst-launch-1.0 v4l2src device=/dev/video0 ! \
video/x-raw,format=YUY2,width=640,height=480,framerate=30/1 ! \
videoconvert ! x264enc tune=zerolatency ! fakesink