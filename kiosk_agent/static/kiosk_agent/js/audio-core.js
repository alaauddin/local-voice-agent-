"use strict";

import { state } from "./state.js";
import { el } from "./dom.js";
import { realtimeEnabled } from "./config.js";

const playback = new Audio();
playback.preload = "auto";
playback.volume = 1;
const ASSISTANT_OUTPUT_GAIN = 1.7;
let outputCtx = null;
let outputGain = null;
let outputSource = null;

function ensureAssistantGain() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return false;
  if (!outputCtx) {
    outputCtx = new AC();
    outputGain = outputCtx.createGain();
    outputGain.gain.value = ASSISTANT_OUTPUT_GAIN;
    outputGain.connect(outputCtx.destination);
  }
  if (!outputSource) {
    try {
      outputSource = outputCtx.createMediaElementSource(playback);
      outputSource.connect(outputGain);
    } catch (error) {
      console.debug("Assistant gain source already connected", error);
    }
  }
  return true;
}

async function resumeOutputContext() {
  if (outputCtx && outputCtx.state === "suspended") {
    try { await outputCtx.resume(); } catch (error) { console.debug("AudioContext resume failed", error); }
  }
}

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
    if (!realtimeEnabled) {
      playback.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAACA";
      playback.muted = false;
      playback.volume = 1;
      await playback.play();
      playback.pause();
      playback.removeAttribute("src");
      playback.load();
      state.audioUnlocked = true;
      return;
    }
    if (realtimeEnabled) {
      ensureAssistantGain();
      await resumeOutputContext();
    }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (AC && !outputCtx) {
      const ctx = new AC();
      if (ctx.state === "suspended") await ctx.resume();
      const buf = ctx.createBuffer(1, 1, 22050);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      src.start(0);
      setTimeout(() => { try { ctx.close(); } catch (_) {} }, 500);
    }
    playback.muted = true;
    const prevVol = playback.volume;
    playback.volume = 0;
    try { await playback.play(); } catch (_) {}
    playback.pause();
    playback.currentTime = 0;
    playback.muted = false;
    playback.volume = 1;
    void prevVol;
    state.audioUnlocked = true;
  } catch (error) {
    console.debug("Audio unlock is waiting for a user gesture", error);
  }
}

export {
  playback, ASSISTANT_OUTPUT_GAIN,
  ensureAssistantGain, resumeOutputContext,
  getPreferredMicId, enumerateMicrophones, populatePreferredMic,
  unlockAudio, preferredMicKey,
};

// re-export mutable gain refs via getters for realtime
export function getOutputGain() { return outputGain; }
