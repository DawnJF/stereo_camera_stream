const APP_ID = "5e881fdc469a4db1b05357c5665d2279";
const CHANNEL = "123";
const TOKEN = "007eJxTYNjsISQupMHHK8Z6LKDJepna2unL9pnyxCiWnjY6MU1j4gcFBtNUCwvDtJRkEzPLRJOUJMMkA1NjU/NkUzMz0xQjI3PL09G7MxsCGRk+6KxlZmSAQBCfmcHQyJiBAQDuDxsY";
const UID = null;
const PROXY_MODE = 0;

let client = null;
let playingRemoteUid = null;
let localTracks = {
  videoTrack: null,
  audioTrack: null,
};

function getConfig() {
  const params = new URLSearchParams(window.location.search);
  const appId = (params.get("appId") || APP_ID).trim();
  const channel = (params.get("channel") || CHANNEL).trim();
  const tokenParam = params.get("token");
  const token = tokenParam ? tokenParam.trim() : TOKEN;
  const uidParam = params.get("uid");
  const uid = uidParam ? uidParam.trim() : UID;
  const proxyModeRaw = params.get("proxyMode") ?? String(PROXY_MODE);
  const proxyMode = Number(proxyModeRaw);
  const codecParam = params.get("codec");
  const publishLocalParam = params.get("publishLocal");
  const publishLocal = publishLocalParam == null ? false : publishLocalParam;
  const codec = codecParam || "vp8";

  return {
    appId,
    channel,
    token,
    uid,
    proxyMode,
    codec,
    publishLocal,
  };
}

function setStatus(text) {
  const el = document.getElementById("status");
  if (el) {
    el.textContent = text;
  }
}

function appendLog(text) {
  const now = new Date();
  const time = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(
    2,
    "0",
  )}:${String(now.getSeconds()).padStart(2, "0")}.${String(now.getMilliseconds()).padStart(3, "0")}`;
  const line = `[${time}] ${text}`;

  const el = document.getElementById("log");
  if (el) {
    el.textContent = `${line}\n${el.textContent || ""}`;
  }
  console.log(line);
}

function clearRemote() {
  const remoteVideoElement = document.getElementById("remote-video");
  if (remoteVideoElement) {
    remoteVideoElement.srcObject = null;
  }
  playingRemoteUid = null;
}

async function subscribeAndPlayRemote(user, mediaType) {
  if (!client) {
    return;
  }

  appendLog(
    `远端 published：uid=${user.uid} mediaType=${mediaType} hasVideo=${!!user.hasVideo} hasAudio=${!!user.hasAudio}`,
  );
  await client.subscribe(user, mediaType);
  appendLog(`订阅成功：uid=${user.uid} mediaType=${mediaType}`);

  if (mediaType === "video") {
    const remoteVideoElement = document.getElementById("remote-video");
    if (!remoteVideoElement) {
      return;
    }

    playingRemoteUid = user.uid;
    if (!user.videoTrack) {
      appendLog(`订阅后 videoTrack 为空：uid=${user.uid}`);
      return;
    }

    const mediaStreamTrack = user.videoTrack.getMediaStreamTrack();
    const mediaStream = new MediaStream([mediaStreamTrack]);
    remoteVideoElement.srcObject = mediaStream;
    remoteVideoElement.play().catch(e => appendLog(`视频播放失败：${e}`));
    setStatus(`已接收远端视频：uid ${user.uid}`);
    appendLog(`开始播放远端视频：uid=${user.uid}`);
  }

  if (mediaType === "audio") {
    if (!user.audioTrack) {
      appendLog(`订阅后 audioTrack 为空：uid=${user.uid}`);
      return;
    }
    user.audioTrack.play();
    appendLog(`开始播放远端音频：uid=${user.uid}`);
  }
}

async function start() {
  const config = getConfig();
  setStatus("初始化中…");
  appendLog(
    `页面参数：channel=${config.channel} uid=${config.uid} codec=${config.codec} proxyMode=${config.proxyMode} publishLocal=${config.publishLocal}`,
  );

  AgoraRTC.onAutoplayFailed = () => {
    setStatus("浏览器阻止自动播放：请点击页面任意位置重试");
    appendLog("触发 onAutoplayFailed");
  };

  client = AgoraRTC.createClient({ mode: "rtc", codec: config.codec });

  client.on("exception", (e) => {
    console.error(e);
    appendLog(`exception: ${e?.message || String(e)}`);
  });

  client.on("connection-state-change", (curState, prevState, reason) => {
    console.log("connection-state-change", { curState, prevState, reason });
    appendLog(`连接状态：${prevState} -> ${curState}${reason ? ` (${reason})` : ""}`);
  });

  client.on("user-joined", (user) => {
    appendLog(`远端加入：uid=${user.uid}`);
  });

  client.on("user-published", async (user, mediaType) => {
    try {
      await subscribeAndPlayRemote(user, mediaType);
    } catch (e) {
      console.error(e);
      appendLog(`订阅失败：uid=${user?.uid} mediaType=${mediaType} err=${e?.message || String(e)}`);
    }
  });

  client.on("user-unpublished", (user, mediaType) => {
    if (mediaType !== "video") {
      return;
    }

    if (playingRemoteUid === user.uid) {
      clearRemote();
      setStatus("远端视频已停止发布");
    }
  });

  client.on("user-left", (user) => {
    if (playingRemoteUid === user.uid) {
      clearRemote();
      setStatus("远端用户已离开");
    }
  });

  if (config.proxyMode !== 0 && !Number.isNaN(config.proxyMode)) {
    try {
      client.startProxyServer(config.proxyMode);
    } catch (e) {
      console.error(e);
    }
  }

  const joinedUid = await client.join(config.appId, config.channel, config.token || null, config.uid);
  setStatus(`已加入频道：${config.channel}，本地 uid ${joinedUid}（codec=${config.codec}）`);
  appendLog(`join 成功：uid=${joinedUid}`);

  if (config.publishLocal) {
    const [audioTrack, videoTrack] = await Promise.all([
      AgoraRTC.createMicrophoneAudioTrack(),
      AgoraRTC.createCameraVideoTrack(),
    ]);
    localTracks.audioTrack = audioTrack;
    localTracks.videoTrack = videoTrack;

    const localContainer = document.getElementById("local-video");
    if (localContainer) {
      localTracks.videoTrack.play("local-video", { mirror: true });
    }

    await client.publish([localTracks.audioTrack, localTracks.videoTrack]);
    setStatus("已发布本地音视频，等待远端发布…");
    appendLog("本地 publish 成功");
  } else {
    setStatus("已加入频道，等待远端发布…");
  }

}

start().catch((err) => {
  console.error(err);
  setStatus(`发生错误：${err?.message || String(err)}`);
});

window.addEventListener("beforeunload", () => {
  try {
    if (localTracks.videoTrack) {
      localTracks.videoTrack.stop();
      localTracks.videoTrack.close();
      localTracks.videoTrack = null;
    }
    if (localTracks.audioTrack) {
      localTracks.audioTrack.stop();
      localTracks.audioTrack.close();
      localTracks.audioTrack = null;
    }
    if (client) {
      client.leave();
      client = null;
    }
  } catch (e) {
    console.error(e);
  }
});
