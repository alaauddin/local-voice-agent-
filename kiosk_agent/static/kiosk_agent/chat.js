"use strict";

import { $, el } from "./js/dom.js";
import { state, fallback } from "./js/state.js";
import { realtimeEnabled } from "./js/config.js";
import { voiceController } from "./js/voice-controller.js";
import {
  populatePreferredMic, unlockAudio, preferredMicKey,
} from "./js/audio-core.js";
import {
  syncAndLoadRemotes, bindRemotesUi, startRemotesRefresh,
} from "./js/remotes.js?v=remote-sync-2";
import {
  setAvatar, preloadAvatarVideos, setMessagesOpen, updateControls, setBusy,
  cancelAutoStart, scheduleAutoRealtime, setConnection, loadMemory,
} from "./js/ui.js";
import { connect } from "./js/socket.js";
import { closeRealtime, startRealtime } from "./js/realtime.js";
import { endConversation, touchConversationTimeout } from "./js/conversation.js";
import {
  configureRecognition, toggleWakeWord,
  stopRecognition, startRecognition, scheduleWakeListener,
} from "./js/recognition.js";
import { speakBrowser } from "./js/speech-output.js";
import { submitMessage, resizeInput, populateVoices, resetStay } from "./js/actions.js";

voiceController.configure({
  closeRealtime, endConversation, scheduleWakeListener, speakBrowser, startRealtime,
  startRecognition, stopRecognition, submitMessage, touchConversationTimeout,
});

bindRemotesUi();


el.form.addEventListener("submit", (event) => { event.preventDefault(); submitMessage(el.input.value); });
document.addEventListener("pointerdown", unlockAudio, { passive: true });
document.addEventListener("keydown", unlockAudio, { passive: true });
el.input.addEventListener("input", resizeInput, {passive:true});
el.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submitMessage(el.input.value); }
});
$("#suggestions").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-message]");
  if (button) submitMessage(button.dataset.message);
});
el.mic.addEventListener("click", toggleWakeWord);
el.messagesToggle.addEventListener("click", () => setMessagesOpen(!state.messagesOpen));
el.closeMessages.addEventListener("click", () => setMessagesOpen(false));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.messagesOpen) setMessagesOpen(false);
});
el.reload?.addEventListener("click", () => window.location.reload());
el.reset.addEventListener("click", () => el.resetDialog.showModal());
el.cancelReset.addEventListener("click", () => el.resetDialog.close());
el.confirmReset.addEventListener("click", resetStay);
el.settingsButton.addEventListener("click", () => el.settingsDialog.showModal());
el.closeSettings.addEventListener("click", () => el.settingsDialog.close());
el.fallbackEnabled.checked = fallback.enabled;
el.speechRate.value = fallback.rate;
el.speechRateValue.textContent = fallback.rate.toFixed(1);
el.fallbackEnabled.addEventListener("change", () => {
  fallback.enabled = el.fallbackEnabled.checked;
  localStorage.setItem("voiceFallbackEnabled", String(fallback.enabled));
});
if (el.preferredMic) {
  populatePreferredMic();
  el.preferredMic.addEventListener("change", () => {
    const id = el.preferredMic.value;
    if (id) localStorage.setItem(preferredMicKey, id);
    else localStorage.removeItem(preferredMicKey);
    console.debug("[Mic] preferred device selected", id ? id.slice(0, 8) : "auto");
    if (state.realtimeReady || state.rtcPeer) {
      console.debug("[Mic] will use new device on next Realtime session");
    }
  });
  if (navigator.mediaDevices?.addEventListener) {
    navigator.mediaDevices.addEventListener("devicechange", populatePreferredMic);
  } else if (navigator.mediaDevices) {
    navigator.mediaDevices.ondevicechange = populatePreferredMic;
  }
  el.settingsButton.addEventListener("click", populatePreferredMic);
}
el.browserVoice.addEventListener("change", () => {
  fallback.voiceURI = el.browserVoice.value;
  localStorage.setItem("voiceFallbackURI", fallback.voiceURI);
});
el.speechRate.addEventListener("input", () => {
  fallback.rate = Number.parseFloat(el.speechRate.value);
  el.speechRateValue.textContent = fallback.rate.toFixed(1);
  localStorage.setItem("voiceFallbackRate", String(fallback.rate));
});
el.testVoice.addEventListener("click", () => speakBrowser("أهلاً وسهلاً بك، أنا غروب وفي خدمتك"));
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    el.avatar.querySelectorAll(".avatar-video").forEach((video) => video.pause());
    stopRecognition();
    if (realtimeEnabled && state.conversationActive) {
      if (state.micAutoStartEnabled) {
        closeRealtime();
        state.conversationActive = false;
        updateControls();
      } else {
        endConversation(false);
      }
    }
    return;
  }
  setAvatar(el.avatar.dataset.state, true);
  if (!state.connected || state.busy) return;
  if (realtimeEnabled && state.micAutoStartEnabled && !state.realtimeReady && !state.rtcPeer) {
    scheduleAutoRealtime(300);
    return;
  }
  if (state.conversationActive && !realtimeEnabled) voiceController.schedule("visibility-recognition", () => startRecognition("command"), 250);
  else scheduleWakeListener(250);
});
window.addEventListener("online", () => setConnection("online", "عاد الاتصال — جاهز لخدمتك"));
window.addEventListener("offline", () => setConnection("offline", "انقطع الإنترنت — سيتم الإرسال تلقائياً عند العودة"));
window.addEventListener("beforeunload", () => {
  cancelAutoStart();
  stopRecognition();
  closeRealtime();
});
if (window.speechSynthesis) {
  populateVoices();
  window.speechSynthesis.onvoiceschanged = populateVoices;
}

setAvatar("idle", true);
preloadAvatarVideos();
configureRecognition();
loadMemory();
syncAndLoadRemotes();
startRemotesRefresh();
connect();
