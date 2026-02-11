import gi
import sys
import os
import time

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

Gst.init(None)

def run_pipeline(pipeline_str, name):
    print(f"[{name}] Starting pipeline: {pipeline_str}")
    try:
        pipeline = Gst.parse_launch(pipeline_str)
    except Exception as e:
        print(f"[{name}] Failed to parse pipeline: {e}")
        return False

    bus = pipeline.get_bus()
    pipeline.set_state(Gst.State.PLAYING)
    
    print(f"[{name}] Running for 5 seconds...")
    start_time = time.time()
    
    # Run loop
    while time.time() - start_time < 5:
        msg = bus.timed_pop_filtered(100 * Gst.MSECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS | Gst.MessageType.STATE_CHANGED)
        if msg:
            if msg.type == Gst.MessageType.ERROR:
                err, debug = msg.parse_error()
                print(f"[{name}] ERROR: {err}")
                print(f"[{name}] DEBUG INFO: {debug}")
                pipeline.set_state(Gst.State.NULL)
                return False
            elif msg.type == Gst.MessageType.EOS:
                print(f"[{name}] EOS reached")
                break
            elif msg.type == Gst.MessageType.STATE_CHANGED:
                old, new, pending = msg.parse_state_changed()
                # print(f"[{name}] State changed from {old.value_nick} to {new.value_nick}")
    
    print(f"[{name}] Finished successfully.")
    pipeline.set_state(Gst.State.NULL)
    return True

def main():
    print("=== GStreamer Camera Diagnostic Tool ===")
    
    # 1. Test basic Raw capability at 1080p
    # Many webcams do NOT support raw YUV at 1080p due to USB bandwidth, they use MJPG.
    print("\n--- Test 1: Raw 1080p 30fps ---")
    res = run_pipeline(
        "v4l2src device=/dev/video0 num-buffers=10 ! video/x-raw,width=1920,height=1080,framerate=30/1 ! videoconvert ! jpegenc ! multifilesink location=test1_raw_%02d.jpg",
        "Test 1"
    )
    if res:
        print(">>> SUCCESS: Camera supports Raw 1080p. Check test1_raw_*.jpg")
    else:
        print(">>> FAILURE: Camera likely does not support Raw 1080p.")

    # 2. Test MJPG capability at 1080p
    print("\n--- Test 2: MJPG 1080p 30fps ---")
    # We decode the MJPG to raw, then re-encode to JPEG for the file sink (just to prove we can process it)
    res = run_pipeline(
        "v4l2src device=/dev/video0 num-buffers=10 ! image/jpeg,width=1920,height=1080,framerate=30/1 ! jpegdec ! videoconvert ! jpegenc ! multifilesink location=test2_mjpg_%02d.jpg",
        "Test 2"
    )
    if res:
        print(">>> SUCCESS: Camera supports MJPG 1080p. Check test2_mjpg_*.jpg")
    else:
        print(">>> FAILURE: Camera likely does not support MJPG 1080p.")

    # 3. Test 720p Raw (Fallback)
    print("\n--- Test 3: Raw 720p 30fps ---")
    res = run_pipeline(
        "v4l2src device=/dev/video0 num-buffers=10 ! video/x-raw,width=1280,height=720,framerate=30/1 ! videoconvert ! jpegenc ! multifilesink location=test3_720p_%02d.jpg",
        "Test 3"
    )
    if res:
        print(">>> SUCCESS: Camera supports Raw 720p. Check test3_720p_*.jpg")
    
    # 4. Test Current Server Pipeline Logic (Simulation)
    # mimicking the exact pipeline in server.py but with fakesink instead of webrtc
    print("\n--- Test 4: Server Pipeline Simulation ---")
    print("Testing the encoding chain used in server.py...")
    # Using tee to dump a frame while encoding
    res = run_pipeline(
        "v4l2src device=/dev/video0 ! video/x-raw,width=1920,height=1080,framerate=30/1 ! "
        "videoconvert ! tee name=t ! queue ! "
        "x264enc tune=zerolatency key-int-max=30 ! fakesink "
        "t. ! queue ! videorate ! video/x-raw,framerate=1/1 ! jpegenc ! multifilesink location=test4_debug_%02d.jpg",
        "Test 4"
    )
    if res:
        print(">>> SUCCESS: Server pipeline simulation works.")
    else:
        print(">>> FAILURE: Server pipeline failed. If Test 1 failed, this is expected.")

if __name__ == "__main__":
    main()
