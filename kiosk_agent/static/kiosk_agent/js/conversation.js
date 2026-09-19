"use strict";

import { el } from "./dom.js";
import { state } from "./state.js";
import { wakeWord, realtimeEnabled } from "./config.js";
import { setAvatar, setBusy, updateControls, scheduleAutoRealtime, cancelAutoStart } from "./ui.js";
import { closeRealtime } from "./realtime.js";
import { stopRecognition, startRecognition, scheduleWakeListener, speakBrowser } from "./voice.js";

export function finishTurn() {
  clearTimeout(state.completionTimer);
  setBusy(false);
  setAvatar("idle");
  if (state.conversationActive && realtimeEnabled) {
    el.voiceStatus.textContent = "تفضل… أنا أستمع";
    touchConversationTimeout();
  } else if (state.conversationActive) {
    el.voiceStatus.textContent = "تفضل… أنا أستمع";
    touchConversationTimeout();
    window.setTimeout(() => startRecognition("command"), 450);
  } else {
    el.voiceStatus.textContent = state.wakeArmed
      ? `قل «${wakeWord}» لبدء المحادثة`
      : `اضغط على الميكروفون للسماح بالاستماع`;
    if (state.wakeArmed) scheduleWakeListener(500);
  }
}

export function touchConversationTimeout() {
  clearTimeout(state.inactivityTimer);
  if (!state.conversationActive) return;
  if (realtimeEnabled && state.micAutoStartEnabled) return;
  state.inactivityTimer = window.setTimeout(() => endConversation(false), 120000);
}

export function endConversation(sayGoodbye = true) {
  clearTimeout(state.inactivityTimer);
  state.conversationActive = false;
  state.pendingCommand = false;
  if (realtimeEnabled) closeRealtime();
  stopRecognition();
  el.interim.textContent = "";
  setAvatar("idle");
  el.voiceStatus.textContent = `قل «${wakeWord}» لبدء محادثة جديدة`;
  updateControls();
  if (realtimeEnabled && state.micAutoStartEnabled && state.connected) {
    el.voiceStatus.textContent = "تفضل… أنا أستمع";
    scheduleAutoRealtime(900);
    return;
  }
  const resumeWake = () => scheduleWakeListener(350);
  if (sayGoodbye) speakBrowser("في أمان الله، أنا هنا متى احتجتني", resumeWake);
  else resumeWake();
}

