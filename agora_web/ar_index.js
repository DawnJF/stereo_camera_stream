
// --- Agora Config ---
const APP_ID = "5e881fdc469a4db1b05357c5665d2279";
const CHANNEL = "123";
const TOKEN = "007eJxTYJDZsMllXplRsevWs5+Psvw+J7+jTP73XaabqznrDYt2PNNQYDBNtbAwTEtJNjGzTDRJSTJMMjA1NjVPNjUzM00xMjK3TDGqyGwIZGQwul7EysgAgSA+M4OhkTEDAwBZtR5p";

// --- Babylon Config ---
const ENABLE_SBS = false; // SBS 开关：true=开启SBS模式, false=关闭SBS模式

// --- Globals ---
let client = null;
const videoElement = document.getElementById('video');
const canvas = document.getElementById("renderCanvas");
const engine = new BABYLON.Engine(canvas, true);

// --- Logger ---
function log(text) {
    const el = document.getElementById("log");
    if (el) {
        el.innerHTML += `<div>${text}</div>`;
        el.scrollTop = el.scrollHeight;
    }
    console.log(text);
}

// --- Agora Logic ---
function getConfig() {
    const params = new URLSearchParams(window.location.search);
    const appId = (params.get("appId") || APP_ID).trim();
    const channel = (params.get("channel") || CHANNEL).trim();
    const tokenParam = params.get("token");
    const token = tokenParam ? tokenParam.trim() : TOKEN;
    const uidParam = params.get("uid");
    const uid = uidParam ? uidParam.trim() : null;
    const codecParam = params.get("codec");
    const codec = codecParam || "vp8";
    
    return {
        appId,
        channel,
        token,
        uid,
        codec
    };
}

async function startAgora() {
    const config = getConfig();
    log(`Initializing Agora... Channel: ${config.channel}`);
    
    client = AgoraRTC.createClient({ mode: "rtc", codec: config.codec });

    client.on("user-published", async (user, mediaType) => {
        await client.subscribe(user, mediaType);
        log(`Subscribed to ${user.uid} ${mediaType}`);

        if (mediaType === "video") {
            const remoteVideoTrack = user.videoTrack;
            const mediaStreamTrack = remoteVideoTrack.getMediaStreamTrack();
            const mediaStream = new MediaStream([mediaStreamTrack]);
            
            // Assign stream to the video element used by Babylon
            videoElement.srcObject = mediaStream;
            videoElement.play().catch(e => log("Video play error: " + e));
            log(`Playing video for ${user.uid}`);
        } else if (mediaType === "audio") {
            user.audioTrack.play();
            log(`Playing audio for ${user.uid}`);
        }
    });

    client.on("user-unpublished", (user, mediaType) => {
        log(`User ${user.uid} unpublished ${mediaType}`);
    });

    client.on("user-left", (user) => {
        log(`User ${user.uid} left`);
    });

    try {
        const uid = await client.join(config.appId, config.channel, config.token || null, config.uid);
        log(`Joined channel as ${uid}`);
    } catch (e) {
        log("Join failed: " + e);
        throw e;
    }
}

// --- Babylon Logic ---
const createScene = async function () {
    const scene = new BABYLON.Scene(engine);
    // AR 模式下背景通常需要透明
    scene.clearColor = new BABYLON.Color4(0, 0, 0, 0);

    const camera = new BABYLON.FreeCamera("camera1", new BABYLON.Vector3(0, 0, 0), scene);

    const videoTexture = new BABYLON.VideoTexture("videoTexture", videoElement, scene, true);
    // 根据 SBS 开关设置纹理缩放
    videoTexture.uScale = ENABLE_SBS ? 0.5 : 1.0; 
    videoTexture.uOffset = 0;

    // 创建一个平面显示视频
    const plane = BABYLON.MeshBuilder.CreatePlane("videoPlane", { width: 2, height: 1.125 }, scene);
    const mat = new BABYLON.StandardMaterial("videoMat", scene);
    mat.diffuseTexture = videoTexture;
    mat.emissiveColor = new BABYLON.Color3(1, 1, 1);
    mat.disableLighting = true;
    mat.backFaceCulling = false;
    plane.material = mat;

    // 固定在相机前方 (HUD 效果)
    scene.onBeforeRenderObservable.add(() => {
        if (scene.activeCamera) {
            plane.parent = scene.activeCamera;
            plane.position.set(0, 0, 2.2); // 距离相机 2.2 米
            plane.rotation.set(0, 0, 0);
        }
    });

    try {
        const xr = await scene.createDefaultXRExperienceAsync({
            uiOptions: {
                sessionMode: "immersive-ar",
            }
        });
        log("AR initialized");
    } catch (e) {
        log("AR not supported (or not in secure context/XR device): " + e);
    }

    return scene;
};

// --- Main Entry ---
document.getElementById('startBtn').addEventListener('click', async () => {
    document.getElementById('startBtn').style.display = 'none';
    
    // Start Agora
    try {
        await startAgora();
    } catch (e) {
        log("Agora Error: " + e);
        // Don't return, let Babylon start anyway so we can see if it works with blank/black texture
    }

    // Start Babylon
    const scene = await createScene();
    engine.runRenderLoop(() => scene.render());
});

window.addEventListener("resize", () => engine.resize());
