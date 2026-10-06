"use strict";

import { el } from "./dom.js";
import { state } from "./state.js";
import { wakeWord, realtimeEnabled, activationMode } from "./config.js";
import { setAvatar, setBusy, updateControls, scheduleAutoRealtime, cancelAutoStart } from "./ui.js";
import { voiceController, VoicePhase } from "./voice-controller.js";

export function finishTurn() {
  voiceController.cancelTimer("voice-completion-watchdog");
  setBusy(false);
  setAvatar("idle");
  if (state.conversationActive && realtimeEnabled) {
    voiceController.transition(VoicePhase.LISTENING);
    el.voiceStatus.textContent = "تفضل… أنا أستمع";
    touchConversationTimeout();
  } else if (state.conversationActive) {
    voiceController.transition(VoicePhase.LISTENING);
    el.voiceStatus.textContent = "تفضل… أنا أستمع";
    touchConversationTimeout();
    voiceController.schedule("recognition-restart", () => {
      voiceController.call("startRecognition", "command");
    }, 450);
  } else {
    voiceController.transition(VoicePhase.IDLE);
    el.voiceStatus.textContent = state.wakeArmed
      ? `قل «${wakeWord}» لبدء المحادثة`
      : `اضغط على الميكروفون للسماح بالاستماع`;
    if (state.wakeArmed) voiceController.call("scheduleWakeListener", 500);
  }
}

export function touchConversationTimeout() {
  voiceController.cancelTimer("conversation-timeout");
  if (!state.conversationActive) return;
  if (realtimeEnabled && state.micAutoStartEnabled) return;
  voiceController.schedule("conversation-timeout", () => endConversation(false), 120000);
}

export function endConversation(sayGoodbye = true) {
  voiceController.cancelTimer("conversation-timeout");
  state.conversationActive = false;
  state.pendingCommand = false;
  if (realtimeEnabled) voiceController.call("closeRealtime");
  else voiceController.invalidateSession({ reason: "conversation_ended" });
  voiceController.call("stopRecognition");
  el.interim.textContent = "";
  setAvatar("idle");
  el.voiceStatus.textContent = activationMode === "button"
    ? "اضغط زر الميكروفون لبدء محادثة جديدة"
    : `قل «${wakeWord}» لبدء محادثة جديدة`;
  updateControls();
  if (realtimeEnabled && state.micAutoStartEnabled && state.connected) {
    el.voiceStatus.textContent = "تفضل… أنا أستمع";
    scheduleAutoRealtime(900);
    return;
  }
  if (activationMode === "button") return;
  const resumeWake = () => voiceController.call("scheduleWakeListener", 350);
  if (sayGoodbye) voiceController.call("speakBrowser", "في أمان الله، أنا هنا متى احتجتني", resumeWake);
  else resumeWake();
}

