"use strict";

import { el } from "./dom.js";
import { state } from "./state.js";
import { apiKey } from "./config.js";
import { getPreferredMicId } from "./audio-core.js";
import { setAvatar, setBusy, updateControls } from "./ui.js";
import { voiceController, VoicePhase } from "./voice-controller.js";

const MAX_RECORD_MS = 30000;
const MAX_BLOB_BYTES = 10 * 1024 * 1024;
const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
];
const RETRYABLE_GUM_ERRORS = new Set([
  "NotFoundError",
  "OverconstrainedError",
  "NotReadableError",
]);

export function isPushToTalkRecording() {
  return state.pttRecording === true;
}

function pickMimeType() {
  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return "";
  return MIME_CANDIDATES.find((mime) => {
    try { return MediaRecorder.isTypeSupported(mime); } catch { return false; }
  }) || "";
}

function gumErrorStatus(error) {
  switch (error?.name) {
    case "NotAllowedError":
      return "الميكروفون محظور — تحقق من إعدادات المتصفح (NotAllowedError)";
    case "NotFoundError":
      return "لا يوجد ميكروفون (NotFoundError)";
    case "NotReadableError":
      return "الميكروفون قيد الاستخدام (NotReadableError)";
    case "OverconstrainedError":
      return "الميكروفون غير مدعوم (OverconstrainedError)";
    default:
      return `تعذر تشغيل الميكروفون (${error?.name || "UnknownError"})`;
  }
}

function stopVad() {
  window.clearInterval(state.pttVadTimer);
  state.pttVadTimer = 0;
  const ctx = state.pttAudioCtx;
  state.pttAudioCtx = null;
  state.pttAnalyser = null;
  if (ctx) ctx.close().catch(() => {});
}

function startVad(stream) {
  stopVad();
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return;
  try {
    const ctx = new Ctx();
    const src = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    src.connect(analyser);
    state.pttAudioCtx = ctx;
    state.pttAnalyser = analyser;
    const buf = new Float32Array(analyser.fftSize);
    const startedAt = performance.now();
    let lastSpeechAt = 0;
    state.pttVadTimer = window.setInterval(() => {
      if (!state.pttRecording) return;
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i += 1) sum += buf[i] * buf[i];
      const rms = Math.sqrt(sum / buf.length);
      const now = performance.now();
      if (now - startedAt < 300) return;
      if (rms >= 0.025) {
        lastSpeechAt = now;
        state.pttSpeechDetected = true;
      }
      const elapsed = now - startedAt;
      if (lastSpeechAt && now - lastSpeechAt >= 1400 && elapsed >= 1200) {
        console.debug("[Voice] ptt auto-send on silence", { rms: Number(rms.toFixed(4)) });
        stopPushToTalk();
      } else if (!lastSpeechAt && elapsed >= 8000 && !state.busy) {
        console.debug("[Voice] ptt no speech detected, cancelling");
        cancelPushToTalk();
        el.voiceStatus.textContent = "لم أسمع شيئاً — اضغط وحاول مجدداً";
        updateControls();
      }
    }, 100);
  } catch (error) {
    console.warn("[Voice] VAD unavailable, manual send only", error);
  }
}

function cleanupRecorder() {
  stopVad();
  window.clearTimeout(state.pttStopTimer);
  state.pttStopTimer = 0;
  const recorder = state.pttRecorder;
  const stream = state.pttStream;
  state.pttRecorder = null;
  state.pttStream = null;
  state.pttRecording = false;
  if (recorder && recorder.state !== "inactive") {
    try { recorder.stop(); } catch { /* already stopped */ }
  }
  if (stream) stream.getTracks().forEach((track) => { try { track.stop(); } catch { /* noop */ } });
  state.pttChunks = [];
  updateControls();
}

export async function startPushToTalk() {
  if (state.pttRecording) return;
  if (typeof MediaRecorder === "undefined") {
    console.warn("[Voice] MediaRecorder is not supported in this browser");
    el.voiceStatus.textContent = "التسجيل الصوتي غير مدعوم في هذا المتصفح";
    return;
  }
  voiceController.call("stopRecognition");
  voiceController.cancelTimer("recognition-restart");
  voiceController.cancelTimer("wake-listener");
  const base = {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
    channelCount: 1,
  };
  const preferredId = getPreferredMicId();
  let stream = null;
  try {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: preferredId ? { ...base, deviceId: { exact: preferredId } } : base,
      });
    } catch (error) {
      if (preferredId && RETRYABLE_GUM_ERRORS.has(error.name)) {
        console.warn(`[Voice] preferred mic failed (${error.name}), retrying without deviceId`);
        stream = await navigator.mediaDevices.getUserMedia({ audio: base });
      } else {
        throw error;
      }
    }
  } catch (error) {
    console.warn("[Voice] ptt getUserMedia failed", { name: error?.name });
    el.voiceStatus.textContent = gumErrorStatus(error);
    updateControls();
    return;
  }
  const mimeType = pickMimeType();
  const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
  state.pttChunks = [];
  state.pttStream = stream;
  state.pttRecorder = recorder;
  recorder.ondataavailable = (event) => {
    if (event.data && event.data.size) state.pttChunks.push(event.data);
  };
  recorder.onstop = () => { void finishPushToTalk(); };
  recorder.onerror = (event) => {
    console.warn("[Voice] MediaRecorder error", event.error || event);
  };
  stream.getAudioTracks().forEach((track) => {
    track.addEventListener("ended", () => {
      if (state.pttRecorder === recorder && state.pttRecording) stopPushToTalk();
    });
  });
  try {
    recorder.start(250);
  } catch (error) {
    console.warn("[Voice] MediaRecorder start failed", error);
    cleanupRecorder();
    el.voiceStatus.textContent = "تعذر بدء التسجيل — حاول مجدداً";
    return;
  }
  state.pttRecording = true;
  state.pttSpeechDetected = false;
  state.conversationActive = true;
  voiceController.transition(VoicePhase.LISTENING);
  voiceController.call("touchConversationTimeout");
  setAvatar("idle");
  el.interim.textContent = "";
  el.voiceStatus.textContent = "تحدث الآن… سأرسل تلقائياً عند انتهائك";
  updateControls();
  startVad(stream);
  console.debug("[Voice] ptt recording started", { mimeType: recorder.mimeType });
  state.pttStopTimer = window.setTimeout(stopPushToTalk, MAX_RECORD_MS);
}

export function stopPushToTalk() {
  if (!state.pttRecording || !state.pttRecorder) return false;
  window.clearTimeout(state.pttStopTimer);
  state.pttStopTimer = 0;
  el.voiceStatus.textContent = "فهمت عليك…";
  try {
    state.pttRecorder.stop();
  } catch (error) {
    console.warn("[Voice] MediaRecorder stop failed", error);
    cleanupRecorder();
  }
  return true;
}

export function cancelPushToTalk() {
  if (!state.pttRecording && !state.pttStream) return;
  console.debug("[Voice] ptt recording cancelled");
  const recorder = state.pttRecorder;
  if (recorder) recorder.onstop = null;
  cleanupRecorder();
}

async function finishPushToTalk() {
  const recorder = state.pttRecorder;
  const stream = state.pttStream;
  const chunks = state.pttChunks;
  state.pttRecorder = null;
  state.pttStream = null;
  state.pttRecording = false;
  stopVad();
  window.clearTimeout(state.pttStopTimer);
  state.pttStopTimer = 0;
  if (stream) stream.getTracks().forEach((track) => { try { track.stop(); } catch { /* noop */ } });
  state.pttChunks = [];
  updateControls();
  const blob = new Blob(chunks, { type: (recorder && recorder.mimeType) || "audio/webm" });
  console.debug("[Voice] ptt recording stopped", { bytes: blob.size, type: blob.type });
  if (!blob.size) {
    el.voiceStatus.textContent = "لم يتم التقاط صوت — اضغط وحاول مجدداً";
    return;
  }
  if (blob.size > MAX_BLOB_BYTES) {
    el.voiceStatus.textContent = "التسجيل طويل جداً — اجعله أقصر";
    return;
  }
  setBusy(true, "فهمت عليك…");
  try {
    const form = new FormData();
    form.append("audio", blob, "ptt.webm");
    const requestHeaders = {};
    if (apiKey) requestHeaders["X-Kiosk-Key"] = apiKey;
    const response = await fetch("/api/v1/kiosk/voice/transcribe/", {
      method: "POST", headers: requestHeaders, body: form,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || data.detail || `HTTP ${response.status}`);
    const transcript = (data.transcript || "").trim();
    setBusy(false);
    if (!transcript) {
      el.voiceStatus.textContent = "لم أسمع شيئاً — اضغط وحاول مجدداً";
      voiceController.call("touchConversationTimeout");
      updateControls();
      return;
    }
    el.interim.textContent = "";
    await voiceController.call("submitMessage", transcript, true);
  } catch (error) {
    console.error("[Voice] ptt transcribe failed", error);
    setBusy(false);
    el.voiceStatus.textContent = "تعذر فهم الصوت — حاول مجدداً";
    voiceController.call("touchConversationTimeout");
    updateControls();
  }
}
