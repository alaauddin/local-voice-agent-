"use strict";

import { state } from "./state.js";
import { el } from "./dom.js";

const playback = new Audio();
playback.preload = "auto";
playback.volume = 1;
playback.autoplay = true;
playback.playsInline = true;

const preferredMicKey = "kioskPreferredMicId";

function getPreferredMicId() {
  return localStorage.getItem(preferredMicKey) || "";
}

async function enumerateMicrophones() {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === "audioinput");
  } catch (error) {
    console.debug("enumerateDevices failed", error);
    return [];
  }
}

async function populatePreferredMic() {
  if (!el.preferredMic) return;
  const mics = await enumerateMicrophones();
  const saved = getPreferredMicId();
  el.preferredMic.replaceChildren();
  const autoOpt = document.createElement("option");
  autoOpt.value = "";
  autoOpt.textContent = "تلقائي (الأفضل متاح)";
  autoOpt.selected = !saved;
  el.preferredMic.append(autoOpt);
  mics.forEach((mic) => {
    const opt = document.createElement("option");
    opt.value = mic.deviceId;
    opt.textContent = mic.label || `ميكروفون ${mic.deviceId.slice(0, 6)}`;
    opt.selected = mic.deviceId === saved;
    el.preferredMic.append(opt);
  });
  if (mics.length && !saved) {
    console.debug("[Mic] available devices", mics.map((m) => ({ id: m.deviceId.slice(0,8), label: m.label })));
  }
}

async function unlockAudio() {
  if (state.audioUnlocked) return;
  try {
    if (playback.srcObject) {
      playback.muted = false;
      await playback.play();
    } else {
      playback.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAACA";
      playback.muted = false;
      playback.volume = 1;
      await playback.play();
      playback.pause();
      playback.removeAttribute("src");
      playback.load();
    }
    playback.muted = false;
    playback.volume = 1;
    state.audioUnlocked = true;
  } catch (error) {
    console.debug("Audio unlock is waiting for a user gesture", error);
  }
}

export {
  playback,
  getPreferredMicId, enumerateMicrophones, populatePreferredMic,
  unlockAudio, preferredMicKey,
};
