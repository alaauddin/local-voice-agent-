"use strict";

import { el } from "./dom.js";
import { state, fallback } from "./state.js";
import { wakeWord, realtimeEnabled, voiceSource, activationMode } from "./config.js";
import { uuid } from "./api.js";
import { normalizeArabic, normalizedWakeWord, endConversationPhrases } from "./text.js";
import { setAvatar, setBusy, updateControls, cancelAutoStart } from "./ui.js";
import { startRealtime } from "./realtime.js";
import { endConversation, touchConversationTimeout } from "./conversation.js";
import { submitMessage } from "./actions.js";

export function speakBrowser(text, done = () => {}, force = false) {
  if ((!force && !fallback.enabled) || !window.speechSynthesis || !text.trim()) { done(); return; }
  const utterance = new SpeechSynthesisUtterance(text.replace(/[*_#`\[\]]/g, ""));
  utterance.rate = fallback.rate;
  utterance.lang = /[\u0600-\u06ff]/.test(text) ? "ar-SA" : "en-US";
  const voice = fallback.voices.find((item) => item.voiceURI === fallback.voiceURI);
  if (voice) utterance.voice = voice;
  utterance.onstart = () => {
    setAvatar("speaking");
    el.voiceStatus.textContent = `${state.persona} يتحدث الآن…`;
  };
  utterance.onend = done;
  utterance.onerror = done;
  window._activeKioskUtterance = utterance;
  window.speechSynthesis.speak(utterance);
}

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
  el.interim.textContent = heard;
  if (
    state.recognitionMode === "wake"
    && finalText.trim()
    && normalizeArabic(finalText).includes(normalizedWakeWord)
  ) {
    const exactIndex = finalText.indexOf(wakeWord);
    const remainder = exactIndex >= 0 ? finalText.slice(exactIndex + wakeWord.length).trim() : "";
    state.pendingCommand = false;
    state.finalHandled = Boolean(remainder);
    state.conversationActive = true;
    touchConversationTimeout();
    stopRecognition();
    if (realtimeEnabled) {
      el.interim.textContent = "";
      startRealtime(remainder);
    } else if (remainder) submitMessage(remainder, true);
    else {
      el.interim.textContent = "";
      el.voiceStatus.textContent = `${state.persona} يرحّب بك…`;
      if (voiceSource === "backend" && state.socket?.readyState === WebSocket.OPEN) {
        setBusy(true, "يحضّر الترحيب الصوتي…");
        state.socket.send(JSON.stringify({ type: "voice.welcome", request_id: uuid() }));
      } else {
        setAvatar("speaking");
        speakBrowser("أهلاً وسهلاً، أنا معك. تفضل.", () => {
          if (!state.conversationActive || state.busy) return;
          setAvatar("idle");
          el.voiceStatus.textContent = "تفضل… أنا أستمع";
          startRecognition("command");
        }, true);
      }
    }
    return;
  }
  if (!realtimeEnabled && state.recognitionMode === "command" && finalText.trim() && !state.finalHandled) {
    const normalizedFinal = normalizeArabic(finalText);
    if (endConversationPhrases.some((phrase) => normalizedFinal.includes(phrase))) {
      state.finalHandled = true;
      stopRecognition();
      endConversation(true);
      return;
    }
    state.finalHandled = true;
    stopRecognition();
    submitMessage(finalText, true);
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
  if (state.pendingCommand) {
    state.pendingCommand = false;
    window.setTimeout(() => startRecognition("command"), 180);
  } else if (endedMode === "wake" && state.wakeArmed && !state.conversationActive && !state.busy) {
    scheduleWakeListener(400);
  } else if (!realtimeEnabled && endedMode === "command" && !state.finalHandled && state.conversationActive && !state.busy) {
    window.setTimeout(() => startRecognition("command"), 400);
  }
}

export function startRecognition(mode) {
  if (realtimeEnabled && (state.realtimeReady || state.rtcPeer)) return;
  if (!state.recognition || state.recognizing || state.busy || !state.connected) return;
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
  if (!state.wakeArmed || state.conversationActive || state.busy || state.recognizing || !state.connected) return;
  window.setTimeout(() => {
    if (state.wakeArmed && !state.conversationActive && !state.busy && !state.recognizing) startRecognition("wake");
  }, delay);
}

export function toggleWakeWord() {
  if (state.conversationActive) {
    state.micAutoStartEnabled = false;
    cancelAutoStart();
    endConversation(false);
    el.voiceStatus.textContent = "الميكروفون متوقف — اضغط للتفعيل";
  } else if (realtimeEnabled) {
    state.micAutoStartEnabled = activationMode === "always_on";
    state.wakeArmed = activationMode === "wake";
    cancelAutoStart();
    stopRecognition();
    startRealtime();
  } else if (state.wakeArmed && state.recognizing) {
    state.conversationActive = true;
    state.pendingCommand = true;
    stopRecognition();
    touchConversationTimeout();
    el.voiceStatus.textContent = "تفضل… أنا أستمع";
  } else {
    state.wakeArmed = true;
    el.voiceStatus.textContent = `جارٍ تفعيل «${wakeWord}»…`;
    startRecognition("wake");
  }
  updateControls();
}
