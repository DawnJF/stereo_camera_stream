import argparse
import asyncio
import json
import logging
import os
import sys
import ssl
from aiohttp import ClientSession, WSMsgType
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCIceCandidate,
    RTCConfiguration,
    RTCIceServer,
)
from aiortc.contrib.signaling import object_from_string, object_to_string

sys.path.append(os.getcwd())
from webRTC.tracks import CameraTrack

# Global state
pcs = {}  # viewer_id -> RTCPeerConnection
camera_track = None  # Share one track instance (or create per peer)


async def run(args):
    global camera_track
    camera_track = CameraTrack()

    server_url = args.server
    print(f"Connecting to {server_url}...")

    async with ClientSession() as session:
        async with session.ws_connect(server_url, ssl=False) as ws:
            print("Connected to Signaling Server")

            # Register as broadcaster
            await ws.send_json({"type": "register", "role": "broadcaster"})

            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")

                    if msg_type == "offer":
                        viewer_id = data.get("from")
                        sdp = data.get("sdp")
                        print(f"Received offer from {viewer_id}")
                        await handle_offer(ws, viewer_id, sdp)

                    elif msg_type == "candidate":
                        viewer_id = data.get("from")
                        candidate_info = data.get("candidate")
                        print(f"Received candidate from {viewer_id}")
                        await handle_candidate(viewer_id, candidate_info)

                    elif msg_type == "viewer_left":
                        viewer_id = data.get("viewer_id")
                        print(f"Viewer {viewer_id} left")
                        await close_pc(viewer_id)

                elif msg_type == WSMsgType.ERROR:
                    print("ws connection closed with exception %s", ws.exception())


async def handle_offer(ws, viewer_id, sdp):
    # STUN configuration
    ice_servers = [RTCIceServer(urls="stun:stun.l.google.com:19302")]
    config = RTCConfiguration(iceServers=ice_servers)

    pc = RTCPeerConnection(configuration=config)
    pcs[viewer_id] = pc

    # Add track
    track = CameraTrack()
    pc.addTrack(track)

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        print(f"ICE connection state for {viewer_id} is {pc.iceConnectionState}")
        if pc.iceConnectionState == "failed":
            await close_pc(viewer_id)

    @pc.on("icegatheringstatechange")
    async def on_icegatheringstatechange():
        print(f"ICE gathering state for {viewer_id} is {pc.iceGatheringState}")

    remote_desc = RTCSessionDescription(sdp=sdp, type="offer")
    await pc.setRemoteDescription(remote_desc)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    # Sending answer
    await ws.send_json(
        {"type": "answer", "sdp": pc.localDescription.sdp, "to": viewer_id}
    )
    print(f"Sent answer to {viewer_id}")


async def handle_candidate(viewer_id, candidate_info):
    pc = pcs.get(viewer_id)
    if pc:
        try:
            if candidate_info.get("candidate"):
                cand = object_from_string(candidate_info["candidate"])
                cand.sdpMid = candidate_info.get("sdpMid")
                cand.sdpMLineIndex = candidate_info.get("sdpMLineIndex")
                await pc.addIceCandidate(cand)
                print(f"Added candidate for {viewer_id}")
        except Exception as e:
            print(f"Error adding candidate: {e}")


async def close_pc(viewer_id):
    if viewer_id in pcs:
        print(f"Closing PC for {viewer_id}")
        await pcs[viewer_id].close()
        del pcs[viewer_id]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--server", default="wss://127.0.0.1:8080/ws", help="Signaling Server URL"
    )
    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run(args))
    except KeyboardInterrupt:
        pass
