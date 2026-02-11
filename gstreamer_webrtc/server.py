import argparse
import asyncio
import json
import logging
import os
import socket
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
    def __init__(self, ws, loop, width=1920, height=1080, framerate=30):
        self.ws = ws
        self.loop = loop  # asyncio loop
        self.width = width
        self.height = height
        self.framerate = framerate
        self.pipeline = None
        self.webrtc = None
        self._pipeline_started = False
        self._h264_pt = None
        # Pipeline will be constructed in start_pipeline

    def start_pipeline(self):
        try:
            # Create pipeline video part as requested
            # Use v4l2src for camera
            pipeline_str = (
                "webrtcbin name=sendrecv bundle-policy=max-bundle "
                f"v4l2src device=/dev/video0 do-timestamp=true ! "
                f"video/x-raw,width={self.width},height={self.height},framerate={self.framerate}/1 ! "
                "videoconvert ! video/x-raw,format=I420 ! "
                f"x264enc tune=zerolatency speed-preset=ultrafast bitrate=2000 bframes=0 key-int-max={self.framerate} ! "
                "h264parse ! video/x-h264,profile=constrained-baseline,stream-format=byte-stream,alignment=au ! "
                "rtph264pay name=pay0 config-interval=1 ! "
                "application/x-rtp,media=video,encoding-name=H264,clock-rate=90000 ! "
                "queue ! sendrecv."
            )

            self.pipeline = Gst.parse_launch(pipeline_str)

            self.webrtc = self.pipeline.get_by_name("sendrecv")
            if not self.webrtc:
                logger.error("Failed to create webrtcbin")
                return False

            pay = self.pipeline.get_by_name("pay0")
            if not pay:
                logger.error("Could not find rtph264pay element")
                return False
            if self._h264_pt is not None:
                pay.set_property("pt", int(self._h264_pt))
                logger.info("Using H264 payload type: %s", self._h264_pt)
            logger.info("Linked rtph264pay to webrtcbin")

            # Connect signals
            self.webrtc.connect("on-negotiation-needed", self.on_negotiation_needed)
            self.webrtc.connect("on-ice-candidate", self.on_ice_candidate)
            self.webrtc.connect(
                "notify::ice-connection-state", self._on_ice_connection_state_notify
            )
            self.webrtc.connect(
                "notify::ice-gathering-state", self._on_ice_gathering_state_notify
            )
            self.webrtc.connect(
                "notify::connection-state", self._on_connection_state_notify
            )
            self.webrtc.connect(
                "notify::signaling-state", self._on_signaling_state_notify
            )

            # Monitor bus for errors
            bus = self.pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self.on_bus_message)

            self.pipeline.set_state(Gst.State.READY)
            self._pipeline_started = True
            logger.info("Pipeline created")
            return True

        except Exception as e:
            logger.error(f"Error starting pipeline: {e}")
            return False

    def on_bus_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error(f"Pipeline Error: {err}: {debug}")
            # Attempt to close the WebSocket gracefully to notify the client
            asyncio.run_coroutine_threadsafe(
                self.ws.close(message=str(err).encode("utf-8")), self.loop
            )
        elif t == Gst.MessageType.WARNING:
            err, debug = message.parse_warning()
            logger.warning(f"Pipeline Warning: {err}: {debug}")

    def stop_pipeline(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        self._pipeline_started = False
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

    def _on_ice_connection_state_notify(self, element, _):
        try:
            state = element.get_property("ice-connection-state")
        except Exception:
            state = None
        logger.info("ICE connection state: %s", state)

    def _on_ice_gathering_state_notify(self, element, _):
        try:
            state = element.get_property("ice-gathering-state")
        except Exception:
            state = None
        logger.info("ICE gathering state: %s", state)

    def _on_connection_state_notify(self, element, _):
        try:
            state = element.get_property("connection-state")
        except Exception:
            state = None
        logger.info("Peer connection state: %s", state)

    def _on_signaling_state_notify(self, element, _):
        try:
            state = element.get_property("signaling-state")
        except Exception:
            state = None
        logger.info("Signaling state: %s", state)

    def _select_h264_pt_from_offer(self, sdp_text: str):
        h264_pts = []
        fmtp = {}

        for line in sdp_text.splitlines():
            line = line.strip()
            if line.startswith("a=rtpmap:") and "H264/90000" in line:
                try:
                    pt = int(line.split("a=rtpmap:", 1)[1].split(" ", 1)[0])
                    h264_pts.append(pt)
                except Exception:
                    continue
            elif line.startswith("a=fmtp:"):
                try:
                    rest = line.split("a=fmtp:", 1)[1]
                    pt_str, params = rest.split(" ", 1)
                    fmtp[int(pt_str)] = params
                except Exception:
                    continue

        if not h264_pts:
            return None

        def score(pt: int) -> tuple:
            params = fmtp.get(pt, "")
            packetization_1 = "packetization-mode=1" in params
            baseline = "profile-level-id=42" in params
            return (packetization_1, baseline, -pt)

        return sorted(h264_pts, key=score, reverse=True)[0]

    def _maybe_resolve_mdns_candidate(self, candidate_str: str) -> str:
        parts = candidate_str.split()
        if len(parts) < 6 or not parts[0].startswith("candidate:"):
            return candidate_str

        address = parts[4]
        if not address.endswith(".local"):
            return candidate_str

        try:
            infos = socket.getaddrinfo(address, None)
        except Exception:
            return candidate_str

        ip = None
        for family, _, _, _, sockaddr in infos:
            if family == socket.AF_INET:
                ip = sockaddr[0]
                break
        if ip is None:
            for family, _, _, _, sockaddr in infos:
                if family == socket.AF_INET6:
                    ip = sockaddr[0]
                    break

        if not ip:
            return candidate_str

        parts[4] = ip
        resolved = " ".join(parts)
        logger.info("Resolved mDNS candidate %s -> %s", address, ip)
        return resolved

    def handle_offer(self, sdp):
        if not self.webrtc:
            logger.info("Received offer")
            self._h264_pt = self._select_h264_pt_from_offer(sdp)
            if self._h264_pt is None:
                logger.warning("No H264 payload type found in offer")
            if not self.start_pipeline():
                logger.error("Failed to start pipeline")
                return
        else:
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
        if structure and structure.has_field("error"):
            logger.error("Could not set remote description")
            return

        logger.info("Remote description set")

        # Create Answer
        promise = Gst.Promise.new_with_change_func(self.on_answer_created, None, None)
        self.webrtc.emit("create-answer", None, promise)

    def on_answer_created(self, promise, _, __):
        promise.wait()
        structure = promise.get_reply()
        if structure and structure.has_field("error"):
            logger.error("Could not create answer")
            return

        if not structure:
            logger.error("No structure returned from create-answer")
            return

        answer = structure.get_value("answer")
        logger.info("Answer created")

        promise = Gst.Promise.new_with_change_func(
            self.on_local_description_set, answer, None
        )
        self.webrtc.emit("set-local-description", answer, promise)

        # Send answer to browser
        sdp_text = answer.sdp.as_text()
        logger.info("Answer SDP:\n%s", sdp_text)
        msg = {"type": "answer", "sdp": sdp_text}
        asyncio.run_coroutine_threadsafe(self.ws.send_json(msg), self.loop)

    def on_local_description_set(self, promise, answer, _):
        promise.wait()
        structure = promise.get_reply()
        if structure and structure.has_field("error"):
            logger.error("Could not set local description")
            return
        logger.info("Local description set")
        if self.pipeline and self._pipeline_started:
            self.pipeline.set_state(Gst.State.PLAYING)
            logger.info("Pipeline playing")

    def handle_candidate(self, candidate_data):
        if not self.webrtc:
            logger.error("WebRTC element not initialized. Cannot handle candidate.")
            return

        candidate = candidate_data.get("candidate")
        sdpMLineIndex = candidate_data.get("sdpMLineIndex")

        if not candidate:
            logger.info("Received empty or null candidate, skipping.")
            return

        candidate = self._maybe_resolve_mdns_candidate(candidate)
        logger.info(f"Received remote candidate: {candidate}")
        self.webrtc.emit("add-ice-candidate", sdpMLineIndex, candidate)


async def index(request):
    with open(os.path.join(ROOT, "index.html"), "r", encoding="utf-8") as f:
        content = f.read()

    # Inject Signaling Mode: Force 'ws'
    content = content.replace("{{SIGNALING_MODE}}", "ws")
    return web.Response(content_type="text/html", text=content)


async def test_page(request):
    with open(os.path.join(ROOT, "test.html"), "r", encoding="utf-8") as f:
        content = f.read()
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
    parser.add_argument("--framerate", type=int, default=30, help="Video framerate")
    args = parser.parse_args()

    app = web.Application()
    app["config"] = args
    app.router.add_get("/", index)
    app.router.add_get("/test", test_page)
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
