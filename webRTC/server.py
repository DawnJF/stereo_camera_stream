import argparse
import asyncio
import json
import logging
import os
import sys
import ssl
import uuid
from aiohttp import web, WSMsgType
from aiortc import RTCPeerConnection, RTCSessionDescription

sys.path.append(os.getcwd())

# Global state for Relay Mode
broadcaster_ws = None
viewers = {}  # id -> ws

# Global state for Local Mode
pcs = set()
CameraTrack = None
camera = None

ROOT = os.path.dirname(__file__)


async def index(request):
    with open(os.path.join(ROOT, "index.html"), "r", encoding="utf-8") as f:
        content = f.read()
    return web.Response(content_type="text/html", text=content)


async def babylon(request):
    with open(os.path.join(ROOT, "babylon_xr.html"), "r", encoding="utf-8") as f:
        content = f.read()
    return web.Response(content_type="text/html", text=content)


async def seethrough(request):
    with open(os.path.join(ROOT, "seethrough.html"), "r", encoding="utf-8") as f:
        content = f.read()

    # Inject Signaling Mode
    mode = request.app["args"].mode
    signaling_mode = "ws" if mode == "relay" else "http"
    content = content.replace("{{SIGNALING_MODE}}", signaling_mode)

    return web.Response(content_type="text/html", text=content)


# --- Local Mode Handlers ---
async def offer(request):
    if request.app["args"].mode != "local":
        return web.Response(
            status=400, text="Server is in Relay Mode. Use WebSocket signaling."
        )

    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs.add(pc)

    # Add camera track
    camera_track = CameraTrack()
    pc.addTrack(camera_track)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state is {pc.connectionState}")
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)
            camera_track.stop()
        elif pc.connectionState == "closed":
            camera_track.stop()

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    # Wait for ICE gathering
    timeout = 5
    start_time = asyncio.get_event_loop().time()
    while pc.iceGatheringState != "complete":
        if asyncio.get_event_loop().time() - start_time > timeout:
            print("ICE gathering timed out")
            break
        await asyncio.sleep(0.1)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        ),
    )


# --- Relay Mode Handlers ---
async def websocket_handler(request):
    global broadcaster_ws
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    viewer_id = str(uuid.uuid4())
    role = None

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = json.loads(msg.data)
                msg_type = data.get("type")

                if msg_type == "register":
                    role = data.get("role")
                    if role == "broadcaster":
                        broadcaster_ws = ws
                        print("Broadcaster registered")
                        # Notify existing viewers? Or wait for them to reconnect?
                        # For now, just register.
                    elif role == "viewer":
                        viewers[viewer_id] = ws
                        print(f"Viewer {viewer_id} registered")
                        # If broadcaster is ready, notify viewer?
                        if broadcaster_ws:
                            await ws.send_json({"type": "camera_ready"})

                elif msg_type == "offer":
                    # Viewer -> Broadcaster
                    if broadcaster_ws:
                        # Append sender ID so broadcaster knows who sent it
                        data["from"] = viewer_id
                        await broadcaster_ws.send_json(data)
                    else:
                        print("No broadcaster available")

                elif msg_type == "answer":
                    # Broadcaster -> Viewer
                    target_id = data.get("to")
                    if target_id in viewers:
                        await viewers[target_id].send_json(data)

                elif msg_type == "candidate":
                    # Any -> Any
                    # If from viewer, send to broadcaster
                    if role == "viewer":
                        if broadcaster_ws:
                            data["from"] = viewer_id
                            await broadcaster_ws.send_json(data)
                    # If from broadcaster, send to target viewer
                    elif role == "broadcaster":
                        target_id = data.get("to")
                        if target_id in viewers:
                            await viewers[target_id].send_json(data)

            elif msg.type == WSMsgType.ERROR:
                print("ws connection closed with exception %s", ws.exception())

    finally:
        if role == "broadcaster":
            broadcaster_ws = None
            print("Broadcaster disconnected")
        elif role == "viewer":
            if viewer_id in viewers:
                del viewers[viewer_id]
            print(f"Viewer {viewer_id} disconnected")
            if broadcaster_ws:
                await broadcaster_ws.send_json(
                    {"type": "viewer_left", "viewer_id": viewer_id}
                )

    return ws


async def on_shutdown(app):
    if app["args"].mode == "local":
        coros = [pc.close() for pc in pcs]
        await asyncio.gather(*coros)
        pcs.clear()
        if camera:
            camera.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="WebRTC Camera Streamer")
    parser.add_argument(
        "--cert-file",
        default="webRTC/cert.pem",
        help="SSL certificate file (for HTTPS)",
    )
    parser.add_argument(
        "--key-file", default="webRTC/key.pem", help="SSL key file (for HTTPS)"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host for HTTP server")
    parser.add_argument("--port", type=int, default=8182, help="Port for HTTP server")
    parser.add_argument(
        "--mode",
        default="local",
        choices=["local", "relay"],
        help="Run mode: local (camera source) or relay (signaling server)",
    )

    args = parser.parse_args()

    # Conditional Import
    if args.mode == "local":
        try:
            from webRTC.tracks import CameraTrack
            from camera_source.agent import camera
        except ImportError as e:
            print(f"Error importing camera modules: {e}")
            print(
                "Ensure you are running on a device with camera support or use --mode relay"
            )
            sys.exit(1)

    app = web.Application()
    app["args"] = args  # Store args in app for handlers to access
    app.on_shutdown.append(on_shutdown)

    app.router.add_get("/", index)
    app.router.add_get("/video", babylon)
    app.router.add_get("/ar", seethrough)
    app.router.add_static("/vendor", os.path.join(ROOT, "vendor"))

    if args.mode == "local":
        app.router.add_post("/offer", offer)
        print(f"Running in LOCAL mode with Camera.")
    else:
        app.router.add_get("/ws", websocket_handler)
        print(f"Running in RELAY mode (Signaling Server).")

    if (
        args.cert_file
        and args.key_file
        and os.path.exists(args.cert_file)
        and os.path.exists(args.key_file)
    ):
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(args.cert_file, args.key_file)
        protocol = "https"
    else:
        ssl_context = None
        protocol = "http"
        print("Warning: Running without HTTPS. WebXR will only work on localhost.")

    print(f"Server started at {protocol}://{args.host}:{args.port}")

    web.run_app(app, host=args.host, port=args.port, ssl_context=ssl_context)

"""

openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

# local mode
python webRTC/server.py
https://127.0.0.1:8182/ar?useStun=false

# websocket relay mode
python3 webRTC/server.py --mode relay

python3 webRTC/pc_client.py --server wss://121.43.243.97:8182/ws

https://121.43.243.97:8182/ar

"""
