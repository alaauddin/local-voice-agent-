"use strict";

import { el } from "./dom.js";
import { state } from "./state.js";
import { wakeWord, realtimeEnabled, voiceSource, activationMode } from "./config.js";
import { normalizeArabic, normalizedWakeWord, endConversationPhrases } from "./text.js";
import { setAvatar, updateControls, cancelAutoStart } from "./ui.js";
import { voiceController, VoicePhase } from "./voice-controller.js";
import {
  startPushToTalk, stopPushToTalk, isPushToTalkRecording,
} from "./push-to-talk.js";

function voiceDebug(...args) {
  console.debug("[Voice]", ...args);
}

export function configureRecognition() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  voiceDebug("configure", {
    hasNative: Boolean(window.SpeechRecognition),
    hasWebkit: Boolean(window.webkitSpeechRecognition),
    activationMode, voiceSource, realtimeEnabled,
  });
  if (!Recognition) {
    console.warn("[Voice] SpeechRecognition is not supported in this browser build");
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
    voiceDebug("onstart", { mode: state.recognitionMode, continuous: state.recognition.continuous });
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
  console.warn("[Voice] recognition error", {
    error: event.error, message: event.message || "",
    mode: state.recognitionMode, conversationActive: state.conversationActive,
  });
  if (["not-allowed", "service-not-allowed"].includes(event.error)) {
    state.wakeArmed = false;
    el.voiceStatus.textContent = `يرجى السماح باستخدام الميكروفون (${event.error})`;
  } else if (event.error === "audio-capture") {
    el.voiceStatus.textContent = "تعذر الوصول إلى الميكروفون — تحقق أنه غير مستخدم (audio-capture)";
  } else if (event.error === "network") {
    el.voiceStatus.textContent = "تعذر خدمة التعرف الصوتي — تحقق من الإنترنت (network)";
  } else if (event.error === "aborted") {
    voiceDebug("recognition aborted (usually a normal stop())", { mode: state.recognitionMode });
  } else if (event.error === "no-speech") {
    voiceDebug("recognition no-speech (silence timeout)", { mode: state.recognitionMode });
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
  voiceDebug("onend", {
    endedMode, sessionDurationMs: Math.round(sessionDuration),
    finalHandled: state.finalHandled, pendingCommand: state.pendingCommand,
    conversationActive: state.conversationActive, busy: state.busy,
    wakeArmed: state.wakeArmed, hidden: document.hidden,
    restartAttempts: state.recognitionRestartAttempts,
  });
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
  } else if (!realtimeEnabled && endedMode === "command" && !state.finalHandled && state.conversationActive && !state.busy
    && !(activationMode === "button")) {
    // Button mode uses server-side push-to-talk; never resurrect browser
    // SpeechRecognition here (it only produces `network` errors on kiosk).
    voiceController.schedule("recognition-restart", () => startRecognition("command"), 400);
  }
}

function startBlockedReason(mode) {
  // Hard guard: button mode uses server-side push-to-talk. Browser
  // SpeechRecognition has no service in kiosk Chromium (`network` error),
  // so it must never start here, regardless of caller.
  if (activationMode === "button" && !realtimeEnabled) return "ptt-mode";
  if (realtimeEnabled && (state.realtimeReady || state.rtcPeer)) return "realtime-active";
  if (document.hidden) return "document-hidden";
  if (!state.recognition) return "no-recognition-object";
  if (state.recognizing) return "already-recognizing";
  if (state.busy) return "busy";
  if (!state.connected) return "offline";
  return "";
}

export function startRecognition(mode) {
  const blocked = startBlockedReason(mode);
  if (blocked) {
    voiceDebug(`startRecognition(${mode}) blocked`, { reason: blocked });
    return;
  }
  state.recognitionMode = mode;
  state.finalHandled = false;
  state.recognition.continuous = mode === "wake";
  voiceDebug(`startRecognition(${mode})`, { continuous: state.recognition.continuous, lang: state.recognition.lang });
  try { state.recognition.start(); } catch (error) { console.warn("[Voice] recognition start failed", error); }
}

export function stopRecognition() {
  if (!state.recognition || !state.recognizing) return;
  voiceDebug("stopRecognition", { mode: state.recognitionMode });
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
  if (activationMode === "button" && !realtimeEnabled) {
    // Chromium kiosk has no SpeechRecognition service (`network` error), so
    // button mode records via MediaRecorder and transcribes server-side.
    // Click starts recording; sending is automatic on silence (a second
    // click sends immediately). The conversation ends via timeout/reset,
    // not by toggling the mic.
    if (isPushToTalkRecording()) {
      stopPushToTalk();
    } else {
      if (!state.conversationActive) {
        state.wakeArmed = false;
        state.conversationActive = true;
        state.pendingCommand = false;
        voiceController.beginSession({ source: voiceSource });
        voiceController.transition(VoicePhase.LISTENING);
        voiceController.call("touchConversationTimeout");
      }
      void startPushToTalk();
    }
    updateControls();
    return;
  }
  if (state.conversationActive) {
    state.micAutoStartEnabled = false;
    cancelAutoStart();
    voiceController.call("endConversation", false);
    el.voiceStatus.textContent = "الميكروفون متوقف — اضغط للتفعيل";
  } else if (activationMode === "button") {
    state.wakeArmed = false;
    state.conversationActive = true;
    state.pendingCommand = false;
    voiceController.beginSession({ source: voiceSource });
    voiceController.transition(VoicePhase.LISTENING);
    voiceController.call("touchConversationTimeout");
    startRecognition("command");
    el.voiceStatus.textContent = "تفضل… أنا أستمع";
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
