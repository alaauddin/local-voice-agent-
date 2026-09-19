"use strict";

import { $, el } from "./dom.js";
import { state, fallback } from "./state.js";
import { realtimeEnabled, activationMode } from "./config.js";
import { headers, uuid } from "./api.js";
import {
  createMessage, setBusy, setMessagesOpen, updateControls, cancelAutoStart,
} from "./ui.js";
import { startRealtime, sendRealtime, persistRealtimeMessage, closeRealtime } from "./realtime.js";
import { stopRecognition, speakBrowser } from "./voice.js";
import { stopAudio } from "./tts.js";
import { touchConversationTimeout, finishTurn } from "./conversation.js";
import { restartSocket } from "./socket.js";

export async function submitMessage(message, fromVoice = false) {
  const clean = message.trim();
  if (!clean || !state.connected || (!realtimeEnabled && state.busy)) return;
  if (fromVoice) touchConversationTimeout();
  el.input.value = "";
  el.interim.textContent = "";
  resizeInput();
  if (realtimeEnabled) {
    if (!state.realtimeReady) {
      await startRealtime(clean);
      return;
    }
    state.currentRequestId = uuid();
    state.toolIterations = 0;
    createMessage("user", clean, state.currentRequestId);
    await persistRealtimeMessage("user", clean, `text-${state.currentRequestId}`, "text");
    if (state.busy) sendRealtime({ type: "response.cancel" });
    sendRealtime({
      type: "conversation.item.create",
      item: { type: "message", role: "user", content: [{ type: "input_text", text: clean }] },
    });
    sendRealtime({ type: "response.create" });
    setBusy(true, "غروب معك…");
    return;
  }
  createMessage("user", clean);
  setBusy(true);
  state.socket.send(JSON.stringify({ type: "chat.message", message: clean, input_mode: fromVoice ? "voice" : "text" }));
}

export function resizeInput() {
  el.input.style.height = "auto";
  el.input.style.height = `${Math.min(el.input.scrollHeight, 140)}px`;
  const counter = document.getElementById("charCount");
  if (counter) counter.textContent = `${el.input.value.length} / 4000`;
  updateControls();
}

export function populateVoices() {
  if (!window.speechSynthesis) return;
  fallback.voices = window.speechSynthesis.getVoices();
  el.browserVoice.replaceChildren();
  [...fallback.voices]
    .sort((a, b) => Number(b.lang.startsWith("ar")) - Number(a.lang.startsWith("ar")))
    .forEach((voice) => {
      const option = document.createElement("option");
      option.value = voice.voiceURI;
      option.textContent = `${voice.name} (${voice.lang})`;
      option.selected = voice.voiceURI === fallback.voiceURI;
      el.browserVoice.append(option);
    });
}

export async function resetStay() {
  el.confirmReset.disabled = true;
  stopRecognition();
  stopAudio();
  closeRealtime();
  state.micAutoStartEnabled = activationMode === "always_on";
  cancelAutoStart();
  try {
    const response = await fetch("/api/v1/kiosk/reset/", { method: "POST", headers: headers(), body: "{}" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    el.messages.querySelectorAll(".message-row").forEach((node) => node.remove());
    state.unreadMessages = 0;
    el.messageCount.hidden = true;
    setMessagesOpen(false);
    state.streams.clear();
    finishTurn();
    el.resetDialog.close();
    restartSocket();
  } catch (error) {
    el.confirmReset.disabled = false;
    el.confirmReset.textContent = "تعذر المسح — حاول مجدداً";
  }
}

