"use strict";

import { el } from "./dom.js";
import { state } from "./state.js";
import { wakeWord, realtimeEnabled, voiceSource, activationMode } from "./config.js";
import { normalizeArabic, normalizedWakeWord, endConversationPhrases } from "./text.js";
import { setAvatar, updateControls, cancelAutoStart } from "./ui.js";
import { voiceController, VoicePhase } from "./voice-controller.js";

export function configureRecognition() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    el.voiceStatus.textContent = "التعرف الصوتي غير مدعوم في هذا المتصفح — الكتابة متاحة دائماً";
    el.mic.title = "التعرف الصوتي غير مدعوم، استخدم الكتابة";
    return;
  }
  state.recognition = new Recognition();
  state.recognition.interimResults = true;
  state.recognition.lang = "ar-SA";
  state.recognition.onstart = () => {
    state.recognizing = true;
    state.recognitionStartedAt = performance.now();
    voiceController.transition(VoicePhase.LISTENING);
    if (state.recognitionMode === "wake") {
      setAvatar("idle");
      el.voiceStatus.textContent = `جاهز — قل «${wakeWord}»`;
    } else {
      setAvatar("idle");
      el.voiceStatus.textContent = "نعم، تفضل… أنا أستمع";
    }
    updateControls();
  };
  state.recognition.onresult = recognitionResult;
  state.recognition.onerror = recognitionError;
  state.recognition.onend = recognitionEnded;
  state.wakeArmed = activationMode === "wake";
  updateControls();
}

export function recognitionResult(event) {
  let interim = "";
  let finalText = "";
  for (let index = event.resultIndex; index < event.results.length; index += 1) {
    const transcript = event.results[index][0].transcript;
    if (event.results[index].isFinal) finalText += transcript;
    else interim += transcript;
  }
  const heard = `${finalText} ${interim}`.trim();
  if (heard) state.recognitionRestartAttempts = 0;
  el.interim.textContent = heard;
  if (
    state.recognitionMode === "wake"
    && finalText.trim()
    && normalizeArabic(finalText).includes(normalizedWakeWord)
  ) {
    const exactIndex = finalText.indexOf(wakeWord);
    const remainder = exactIndex >= 0 ? finalText.slice(exactIndex + wakeWord.length).trim() : "";
    state.pendingCommand = !remainder && !realtimeEnabled;
    state.finalHandled = Boolean(remainder);
    state.conversationActive = true;
    if (!realtimeEnabled) voiceController.beginSession({ source: voiceSource });
    voiceController.transition(VoicePhase.LISTENING);
    voiceController.call("touchConversationTimeout");
    stopRecognition();
    if (realtimeEnabled) {
      el.interim.textContent = "";
      voiceController.call("startRealtime", remainder);
    } else if (remainder) voiceController.call("submitMessage", remainder, true);
    else {
      el.interim.textContent = "";
      el.voiceStatus.textContent = "تفضل… أنا أستمع";
    }
    return;
  }
  if (!realtimeEnabled && state.recognitionMode === "command" && finalText.trim() && !state.finalHandled) {
    const normalizedFinal = normalizeArabic(finalText);
    if (endConversationPhrases.some((phrase) => normalizedFinal.includes(phrase))) {
      state.finalHandled = true;
      stopRecognition();
      voiceController.call("endConversation", true);
      return;
    }
    state.finalHandled = true;
    stopRecognition();
    voiceController.call("submitMessage", finalText, true);
  }
}

export function recognitionError(event) {
  state.recognizing = false;
  if (["not-allowed", "service-not-allowed"].includes(event.error)) {
    state.wakeArmed = false;
    el.voiceStatus.textContent = "يرجى السماح باستخدام الميكروفون";
  } else if (state.recognitionMode === "command") {
    el.voiceStatus.textContent = state.conversationActive
      ? "ما زلت معك… تفضل"
      : `قل «${wakeWord}» لبدء المحادثة`;
  }
  updateControls();
}

export function recognitionEnded() {
  const endedMode = state.recognitionMode;
  state.recognizing = false;
  state.recognitionMode = null;
  updateControls();
  const sessionDuration = performance.now() - state.recognitionStartedAt;
  if (endedMode === "wake" && sessionDuration < 5000) {
    state.recognitionRestartAttempts += 1;
  } else {
    state.recognitionRestartAttempts = 0;
  }
  const wakeRestartDelay = Math.min(750 * (2 ** state.recognitionRestartAttempts), 10000);
  if (state.pendingCommand) {
    state.pendingCommand = false;
    voiceController.schedule("recognition-restart", () => startRecognition("command"), 180);
  } else if (!document.hidden && endedMode === "wake" && state.wakeArmed && !state.conversationActive && !state.busy) {
    scheduleWakeListener(wakeRestartDelay);
  } else if (!realtimeEnabled && endedMode === "command" && !state.finalHandled && state.conversationActive && !state.busy) {
    voiceController.schedule("recognition-restart", () => startRecognition("command"), 400);
  }
}

export function startRecognition(mode) {
  if (realtimeEnabled && (state.realtimeReady || state.rtcPeer)) return;
  if (document.hidden || !state.recognition || state.recognizing || state.busy || !state.connected) return;
  state.recognitionMode = mode;
  state.finalHandled = false;
  state.recognition.continuous = mode === "wake";
  try { state.recognition.start(); } catch (error) { console.debug("Recognition start delayed", error); }
}

export function stopRecognition() {
  if (!state.recognition || !state.recognizing) return;
  try { state.recognition.stop(); } catch (error) { console.debug("Recognition already stopped", error); }
}

export function scheduleWakeListener(delay = 250) {
  if (realtimeEnabled && (state.realtimeReady || state.rtcPeer)) return;
  if (document.hidden || !state.wakeArmed || state.conversationActive || state.busy || state.recognizing || !state.connected) return;
  voiceController.schedule("wake-listener", () => {
    if (!document.hidden && state.wakeArmed && !state.conversationActive && !state.busy && !state.recognizing) {
      startRecognition("wake");
    }
  }, delay);
}

export function toggleWakeWord() {
  if (state.conversationActive) {
    state.micAutoStartEnabled = false;
    cancelAutoStart();
    voiceController.call("endConversation", false);
    el.voiceStatus.textContent = "الميكروفون متوقف — اضغط للتفعيل";
  } else if (realtimeEnabled) {
    state.micAutoStartEnabled = activationMode === "always_on";
    state.wakeArmed = activationMode === "wake";
    cancelAutoStart();
    stopRecognition();
    voiceController.call("startRealtime");
  } else if (state.wakeArmed && state.recognizing) {
    state.conversationActive = true;
    state.pendingCommand = true;
    voiceController.beginSession({ source: voiceSource });
    voiceController.transition(VoicePhase.LISTENING);
    stopRecognition();
    voiceController.call("touchConversationTimeout");
    el.voiceStatus.textContent = "تفضل… أنا أستمع";
  } else {
    state.wakeArmed = true;
    el.voiceStatus.textContent = `جارٍ تفعيل «${wakeWord}»…`;
    startRecognition("wake");
  }
  updateControls();
}
