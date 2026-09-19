"use strict";

import { el } from "./dom.js";
import { state } from "./state.js";
import { playback } from "./audio-core.js";
import { setAvatar } from "./ui.js";
import { speakBrowser } from "./voice.js";
import { finishTurn } from "./conversation.js";

export function resetAudio(nonce, total = 0) {
  stopAudio();
  state.activeNonce = nonce;
  state.audioBuffer = new Map();
  state.nextSeq = 0;
  state.totalSeq = total || 0;
  state.ttsEnded = false;
}

export function receiveChunk(event) {
  if (state.activeNonce && event.nonce !== state.activeNonce) return;
  if (!state.activeNonce) resetAudio(event.nonce, event.total);
  state.totalSeq = event.total || state.totalSeq;
  state.audioBuffer.set(event.seq, event.fallbackText
    ? { type: "speech", value: event.fallbackText }
    : {
        type: "audio",
        value: `data:${event.content_type || "audio/mpeg"};base64,${event.audio}`,
        fallbackText: event.text || "",
      });
  playNext();
}

export function playNext() {
  if (state.audioPlaying) return;
  const chunk = state.audioBuffer.get(state.nextSeq);
  if (!chunk) {
    if (state.ttsEnded && state.nextSeq >= state.totalSeq) finishTurn();
    return;
  }
  state.audioBuffer.delete(state.nextSeq);
  state.audioPlaying = true;
  setAvatar("thinking");
  el.voiceStatus.textContent = "يبدأ تشغيل الرد الصوتي…";
  if (chunk.type === "speech") {
    speakBrowser(chunk.value, chunkFinished, true);
    return;
  }
  const audio = playback;
  // Backend MP3 must play directly. A suspended AudioContext can make a
  // successfully playing media element completely silent.
  audio.src = chunk.value;
  audio.muted = false;
  audio.volume = 1;
  state.activeAudio = audio;
  let settled = false;
  const finishOnce = () => {
    if (settled) return;
    settled = true;
    chunkFinished();
  };
  audio.onended = finishOnce;
  const useFallback = () => {
    if (settled) return;
    settled = true;
    audio.onended = null;
    audio.onerror = null;
    state.activeAudio = null;
    console.warn("Server audio could not be played; using browser speech fallback");
    if (chunk.fallbackText) speakBrowser(chunk.fallbackText, chunkFinished, true);
    else chunkFinished();
  };
  audio.onerror = useFallback;
  audio.play().then(() => {
    state.audioUnlocked = true;
    setAvatar("speaking");
    el.voiceStatus.textContent = `${state.persona} يتحدث الآن…`;
  }).catch(useFallback);
}

export function chunkFinished() {
  state.audioPlaying = false;
  state.activeAudio = null;
  state.nextSeq += 1;
  playNext();
}

export function stopAudio() {
  if (state.activeAudio) {
    state.activeAudio.pause();
    state.activeAudio.src = "";
  }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  state.activeAudio = null;
  state.audioPlaying = false;
  state.audioBuffer.clear();
}

