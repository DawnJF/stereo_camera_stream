#include <gst/gst.h>
#include <iostream>

int main(int argc, char *argv[])
{
    gst_init(&argc, &argv);

    const char *pipeline_str =
        "v4l2src device=/dev/video0 io-mode=2 ! "
        "image/jpeg,width=3840,height=1080,framerate=30/1 ! "
        "jpegparse ! "
        "nvjpegdec ! "
        "video/x-raw(memory:NVMM),format=NV12 ! "
        "nvv4l2h264enc "
        "bitrate=6000000 "
        "iframeinterval=15 "
        "insert-sps-pps=true "
        "control-rate=1 "
        "preset-level=1 "
        "EnableTwopassCBR=false "
        "zerolatency=true "
        "! h264parse config-interval=1 ! "
        "rtspclientsink location=rtsp://127.0.0.1:8554/test";

    GError *error = nullptr;
    GstElement *pipeline = gst_parse_launch(pipeline_str, &error);

    if (!pipeline)
    {
        std::cerr << "Pipeline error: " << error->message << std::endl;
        return -1;
    }

    gst_element_set_state(pipeline, GST_STATE_PLAYING);

    GstBus *bus = gst_element_get_bus(pipeline);
    GstMessage *msg = nullptr;

    while (true)
    {
        msg = gst_bus_timed_pop_filtered(
            bus,
            GST_CLOCK_TIME_NONE,
            (GstMessageType)(GST_MESSAGE_ERROR | GST_MESSAGE_EOS));

        if (msg != nullptr)
        {
            GError *err;
            gchar *debug;

            switch (GST_MESSAGE_TYPE(msg))
            {
            case GST_MESSAGE_ERROR:
                gst_message_parse_error(msg, &err, &debug);
                std::cerr << "Error: " << err->message << std::endl;
                g_error_free(err);
                g_free(debug);
                break;
            case GST_MESSAGE_EOS:
                std::cout << "End of stream" << std::endl;
                break;
            default:
                break;
            }
            gst_message_unref(msg);
            break;
        }
    }

    gst_object_unref(bus);
    gst_element_set_state(pipeline, GST_STATE_NULL);
    gst_object_unref(pipeline);

    return 0;
}

// 编译：g++ main.cpp -o gst_video $(pkg-config --cflags --libs gstreamer-1.0)
// 运行：./gst_video