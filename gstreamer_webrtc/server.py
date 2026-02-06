import argparse
import asyncio
import json
import logging
import os
import sys
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstWebRTC", "1.0")
gi.require_version("GstSdp", "1.0")
from gi.repository import Gst, GstWebRTC, GstSdp, GLib

from aiohttp import web, WSMsgType

# Initialize GStreamer
Gst.init(None)

ROOT = os.path.dirname(__file__)
logger = logging.getLogger("gst-webrtc")


class WebRTCClient:
    def __init__(self, ws, loop, width=1920, height=1080, framerate=60):
        self.ws = ws
        self.loop = loop  # asyncio loop
        self.pipeline = None
        self.webrtc = None
        self.pipe_desc = (
            f"v4l2src device=/dev/video0 ! video/x-raw,width={width},height={height},framerate={framerate}/1 ! "
            "nvvideoconvert ! "
            "nvv4l2h264enc bitrate=10_000_000 insert-sps-pps=true ! "
            "h264parse ! "
            "rtph264pay config-interval=-1 ! "
            "application/x-rtp,media=video,encoding-name=H264,payload=96 ! "
            "webrtcbin name=sendrecv bundle-policy=max-bundle"
        )

    def start_pipeline(self):
        try:
            self.pipeline = Gst.parse_launch(self.pipe_desc)
            self.webrtc = self.pipeline.get_by_name("sendrecv")

            # Connect signals
            self.webrtc.connect("on-negotiation-needed", self.on_negotiation_needed)
            self.webrtc.connect("on-ice-candidate", self.on_ice_candidate)

            # Start pipeline
            self.pipeline.set_state(Gst.State.PLAYING)
            logger.info("Pipeline started")

        except Exception as e:
            logger.error(f"Error starting pipeline: {e}")

    def stop_pipeline(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        logger.info("Pipeline stopped")

    def on_negotiation_needed(self, element):
        # We are the answerer, so we don't usually initiate unless we want to renegotiate.
        # But if we were the offerer, we would create an offer here.
        pass

    def on_ice_candidate(self, element, mlineindex, candidate):
        candidate_str = candidate
        logger.info(f"Local ICE candidate: {candidate_str}")

        # Send to browser via WS
        msg = {
            "type": "candidate",
            "candidate": {"candidate": candidate_str, "sdpMLineIndex": mlineindex},
        }
        asyncio.run_coroutine_threadsafe(self.ws.send_json(msg), self.loop)

    def handle_offer(self, sdp):
        logger.info("Received offer")
        res, sm = GstSdp.SDPMessage.new_from_text(sdp)
        rd = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.OFFER, sm)

        promise = Gst.Promise.new_with_change_func(
            self.on_remote_description_set, rd, None
        )
        self.webrtc.emit("set-remote-description", rd, promise)

    def on_remote_description_set(self, promise, rd, _):
        promise.wait()
        structure = promise.get_reply()
        if structure.has_field("error"):
            logger.error("Could not set remote description")
            return

        logger.info("Remote description set")

        # Create Answer
        promise = Gst.Promise.new_with_change_func(self.on_answer_created, None, None)
        self.webrtc.emit("create-answer", None, promise)

    def on_answer_created(self, promise, _, __):
        promise.wait()
        structure = promise.get_reply()
        if structure.has_field("error"):
            logger.error("Could not create answer")
            return

        answer = structure.get_value("answer")
        logger.info("Answer created")

        promise = Gst.Promise.new_with_change_func(
            self.on_local_description_set, answer, None
        )
        self.webrtc.emit("set-local-description", answer, promise)

        # Send answer to browser
        sdp_text = answer.sdp.as_text()
        msg = {"type": "answer", "sdp": sdp_text, "type": "answer"}
        asyncio.run_coroutine_threadsafe(self.ws.send_json(msg), self.loop)

    def on_local_description_set(self, promise, answer, _):
        promise.wait()
        structure = promise.get_reply()
        if structure.has_field("error"):
            logger.error("Could not set local description")
            return
        logger.info("Local description set")

    def handle_candidate(self, candidate_data):
        candidate = candidate_data.get("candidate")
        sdpMLineIndex = candidate_data.get("sdpMLineIndex")

        logger.info(f"Received remote candidate: {candidate}")
        self.webrtc.emit("add-ice-candidate", sdpMLineIndex, candidate)


async def index(request):
    with open(os.path.join(ROOT, "index.html"), "r", encoding="utf-8") as f:
        content = f.read()

    # Inject Signaling Mode: Force 'ws'
    content = content.replace("{{SIGNALING_MODE}}", "ws")
    return web.Response(content_type="text/html", text=content)


async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    logger.info("WebSocket connected")

    # Create a WebRTC client for this connection
    # Note: For simplicity, we create a new pipeline per connection.
    # Be aware that v4l2src might be busy if multiple clients connect.
    # A robust solution would use tee/interpipes, but for this task we assume 1 client.
    config = request.app.get("config")
    if config:
        client = WebRTCClient(
            ws,
            asyncio.get_event_loop(),
            width=config.width,
            height=config.height,
            framerate=config.framerate,
        )
    else:
        client = WebRTCClient(ws, asyncio.get_event_loop())

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = json.loads(msg.data)
                msg_type = data.get("type")

                if msg_type == "register":
                    logger.info("Client registered")
                    # Start pipeline immediately or wait for offer?
                    # Start it so it's ready.
                    client.start_pipeline()

                elif msg_type == "offer":
                    client.handle_offer(data["sdp"])

                elif msg_type == "candidate":
                    client.handle_candidate(data["candidate"])

            elif msg.type == WSMsgType.ERROR:
                logger.error(f"WS connection closed with exception {ws.exception()}")

    finally:
        logger.info("WebSocket disconnected")
        client.stop_pipeline()

    return ws


# GMainLoop Thread
def gst_loop_runner(loop):
    loop.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8182)
    parser.add_argument("--cert-file", default="webRTC/cert.pem")
    parser.add_argument("--key-file", default="webRTC/key.pem")
    parser.add_argument("--width", type=int, default=1920, help="Video width")
    parser.add_argument("--height", type=int, default=1080, help="Video height")
    parser.add_argument("--framerate", type=int, default=60, help="Video framerate")
    args = parser.parse_args()

    app = web.Application()
    app["config"] = args
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket_handler)

    # Map vendor directory from original path
    # ROOT is .../gstreamer_webrtc
    # We want .../webRTC/vendor
    vendor_path = os.path.join(ROOT, "../webRTC", "vendor")
    if os.path.exists(vendor_path):
        app.router.add_static("/vendor", vendor_path)
    else:
        # Fallback to checking CWD just in case
        vendor_path_cwd = os.path.join(os.getcwd(), "webRTC", "vendor")
        if os.path.exists(vendor_path_cwd):
            app.router.add_static("/vendor", vendor_path_cwd)
        else:
            logger.warning("webRTC/vendor not found. Babylon.js might fail to load.")

    # Start GMainLoop in a separate thread
    mainloop = GLib.MainLoop()
    t = threading.Thread(target=gst_loop_runner, args=(mainloop,))
    t.daemon = True
    t.start()

    # SSL Context
    if os.path.exists(args.cert_file) and os.path.exists(args.key_file):
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(args.cert_file, args.key_file)
        protocol = "https"
    else:
        ssl_context = None
        protocol = "http"
        logger.warning("No SSL cert found. Using HTTP.")

    logger.info(f"Server started at {protocol}://0.0.0.0:{args.port}")
    web.run_app(app, host="0.0.0.0", port=args.port, ssl_context=ssl_context)
