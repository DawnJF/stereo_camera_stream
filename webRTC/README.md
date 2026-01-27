### How to Run Scenario 1: Public Internet (New)
You need to run three components:

1. On the Public Server (Signaling) :
   Run the server in relay mode. This serves the HTML page and handles the connection brokering.
   
   ```
   python webRTC/server.py --mode relay 
   --host 0.0.0.0 --port 8182 --cert-file 
   webRTC/cert.pem --key-file webRTC/key.
   pem
   ```
   Note: Ensure you have valid SSL certificates ( cert.pem , key.pem ) as WebXR requires HTTPS.
2. On the PC with Camera (Broadcaster) :
   Run the new client script. This captures the camera and connects to your public server.
   
   ```
   python webRTC/pc_client.py --server 
   wss://<YOUR_PUBLIC_SERVER_IP>:8182/ws
   ```
3. On the Mobile Phone (Viewer) :
   Open the browser and visit: https://<YOUR_PUBLIC_SERVER_IP>:8182/ar?useStun=true Note: Adding ?useStun=true is recommended for public internet connections to penetrate NATs. Scenario 2: Local Network (Existing)
The original functionality is fully preserved. You can run the server directly on the device with the camera:

```
python webRTC/server.py --mode local
# Or simply (defaults to local)
python webRTC/server.py
```
Then visit https://<LOCAL_IP>:8182/ar on your phone.