"use strict";

import { el } from "./dom.js";
import { state } from "./state.js";
import { apiKey, realtimeEnabled, activationMode } from "./config.js";
import { headers, uuid, postJson } from "./api.js";
import {
  playback, ensureAssistantGain, resumeOutputContext, getPreferredMicId,
  ASSISTANT_OUTPUT_GAIN, getOutputGain,
} from "./audio-core.js";
import {
  setAvatar, setBusy, updateControls, scrollBottom, createMessage,
  cancelAutoStart, scheduleAutoRealtime,
} from "./ui.js";
import { stopRecognition, scheduleWakeListener, speakBrowser } from "./voice.js";
import { endConversation, touchConversationTimeout } from "./conversation.js";

export function sendRealtime(event) {
  if (!state.rtcChannel || state.rtcChannel.readyState !== "open") return false;
  state.rtcChannel.send(JSON.stringify(event));
  return true;
}

export function noteFirstAudioLatency() {
  if (!state.turnStoppedAt) return;
  console.debug(
    `Realtime first-audio latency: ${Math.round(performance.now() - state.turnStoppedAt)}ms`,
  );
  state.turnStoppedAt = 0;
}

export function persistRealtimeMessage(role, content, eventId, inputMode = "realtime") {
  const clean = (content || "").trim();
  if (!clean || !state.currentRequestId) return Promise.resolve();
  return postJson("/api/v1/kiosk/realtime/messages/", {
    stay_id: state.currentStayId,
    session_id: state.localSessionId,
    request_id: state.currentRequestId,
    role,
    content: clean,
    event_id: eventId || uuid(),
    input_mode: inputMode,
  }).catch((error) => console.error("Unable to persist realtime message", error));
}

export function extractResponseTranscript(response) {
  return (response?.output || []).flatMap((item) => item.content || [])
    .map((part) => part.transcript || part.text || "")
    .join("")
    .trim();
}

export async function runRealtimeTools(calls) {
  if (!state.currentRequestId) state.currentRequestId = uuid();
  for (const call of calls) {
    state.toolIterations += 1;
    setBusy(true, "يرتّب طلبك الآن…");
    let output;
    if (state.toolIterations > 5) {
      output = { ok: false, error: "tool_iteration_limit" };
    } else {
      try {
        output = await postJson("/api/v1/kiosk/realtime/tools/", {
          stay_id: state.currentStayId,
          session_id: state.localSessionId,
          request_id: state.currentRequestId,
          call_id: call.call_id,
          name: call.name,
          arguments: JSON.parse(call.arguments || "{}"),
        });
      } catch (error) {
        output = { ok: false, error: "tool_execution_failed" };
        console.error("Realtime tool failed", error);
      }
    }
    sendRealtime({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: call.call_id,
        output: JSON.stringify(output),
      },
    });
  }
  sendRealtime({ type: "response.create" });
}

export async function handleRealtimeEvent(event) {
  switch (event.type) {
    case "session.created":
    case "session.updated":
      console.debug(`[Realtime] ${event.type}`);
      return;
    case "input_audio_buffer.speech_started":
      console.debug("[Realtime] speech_started", { at: Math.round(performance.now()) });
      // Cut the assistant audio locally before its tail can leak back into the
      // microphone. Server VAD still handles cancelling the active response.
      playback.muted = true;
      state.outputAudioActive = false;
      state.responseComplete = false;
      state.currentRequestId = uuid();
      state.toolIterations = 0;
      state.assistantTranscript = "";
      state.assistantTarget = null;
      touchConversationTimeout();
      setBusy(false);
      setAvatar("idle");
      el.voiceStatus.textContent = "أنا أسمعك…";
      return;
    case "input_audio_buffer.speech_stopped":
      console.debug("[Realtime] speech_stopped", { at: Math.round(performance.now()), turnStoppedAt: Math.round(performance.now()) });
      state.turnStoppedAt = performance.now();
      setBusy(true, "فهمت عليك…");
      return;
    case "conversation.item.input_audio_transcription.delta":
      el.interim.textContent += event.delta || "";
      return;
    case "conversation.item.input_audio_transcription.completed": {
      const transcript = (event.transcript || "").trim();
      console.debug("[Realtime] transcription completed", { transcript, len: transcript.length, item_id: event.item_id });
      el.interim.textContent = "";
      if (transcript) {
        createMessage("user", transcript, state.currentRequestId);
        await persistRealtimeMessage("user", transcript, event.item_id, "voice");
      }
      return;
    }
    case "response.created":
      console.debug("[Realtime] response created", { id: event.response?.id || event.response_id || "", at: Math.round(performance.now()) });
      state.responseStartedAt = performance.now();
      state.responseComplete = false;
      setBusy(true, "غروب معك…");
      return;
    case "output_audio_buffer.started":
      console.debug("[Realtime] output_audio_buffer.started");
      noteFirstAudioLatency();
      playback.muted = false;
      state.outputAudioActive = true;
      setBusy(false);
      setAvatar("speaking");
      el.voiceStatus.textContent = `${state.persona} يتحدث الآن… قاطعه متى شئت`;
      return;
    case "output_audio_buffer.stopped":
    case "output_audio_buffer.cleared":
      state.outputAudioActive = false;
      if (state.responseComplete) {
        setAvatar("idle");
        el.voiceStatus.textContent = "تفضل… أنا أستمع";
      }
      return;
    case "response.output_audio.delta":
    case "response.audio.delta":
      noteFirstAudioLatency();
      playback.muted = false;
      setBusy(false);
      setAvatar("speaking");
      el.voiceStatus.textContent = `${state.persona} يتحدث الآن… قاطعه متى شئت`;
      return;
    case "response.output_audio_transcript.delta":
    case "response.audio_transcript.delta": {
      if (!state.currentRequestId) state.currentRequestId = uuid();
      if (!state.assistantTarget) {
        state.assistantTarget = createMessage("assistant", "", state.currentRequestId);
      }
      const delta = event.delta || "";
      state.assistantTranscript += delta;
      state.assistantTarget.textContent += delta;
      scrollBottom();
      return;
    }
    case "response.output_audio_transcript.done":
    case "response.audio_transcript.done":
      if (event.transcript) state.assistantTranscript = event.transcript;
      state.assistantEventId = event.item_id || event.response_id || uuid();
      return;
    case "response.done": {
      state.responseComplete = true;
      const calls = (event.response?.output || []).filter((item) => item.type === "function_call");
      if (calls.length) {
        await runRealtimeTools(calls);
        return;
      }
      const transcript = state.assistantTranscript || extractResponseTranscript(event.response);
      if (transcript) {
        if (!state.assistantTarget) {
          state.assistantTarget = createMessage("assistant", transcript, state.currentRequestId);
        } else if (!state.assistantTarget.textContent) {
          state.assistantTarget.textContent = transcript;
        }
        await persistRealtimeMessage(
          "assistant", transcript, state.assistantEventId || event.response?.id, "realtime",
        );
      }
      state.assistantTranscript = "";
      state.assistantTarget = null;
      state.assistantEventId = "";
      setBusy(false);
      if (!state.outputAudioActive) setAvatar("idle");
      el.voiceStatus.textContent = "تفضل… أنا أستمع";
      touchConversationTimeout();
      return;
    }
    case "error":
      console.error("OpenAI Realtime error", event.error || event);
      setBusy(false);
      el.voiceStatus.textContent = "تعذر إكمال الرد، تفضل بالمحاولة مرة أخرى";
      return;
    default:
      return;
  }
}

export function closeRealtime() {
  const closingSessionId = state.localSessionId;
  const closingStayId = state.currentStayId;
  state.realtimeReady = false;
  if (state.rtcChannel) state.rtcChannel.close();
  if (state.rtcPeer) state.rtcPeer.close();
  if (state.rtcStream) state.rtcStream.getTracks().forEach((track) => track.stop());
  if (playback.srcObject) {
    playback.pause();
    playback.srcObject = null;
  }
  state.rtcChannel = null;
  state.rtcPeer = null;
  state.rtcStream = null;
  state.localSessionId = null;
  state.currentRequestId = null;
  state.assistantTranscript = "";
  state.assistantTarget = null;
  state.outputAudioActive = false;
  state.responseComplete = false;
  if (closingSessionId && closingStayId) {
    fetch("/api/v1/kiosk/realtime/session/close/", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({
        session_id: closingSessionId,
        stay_id: closingStayId,
      }),
      keepalive: true,
    }).catch(() => {});
  }
}

export function startRealtime(initialText = "") {
  if (state.connectionPromise) return state.connectionPromise;
  if (!realtimeEnabled || state.realtimeReady || state.rtcPeer) return Promise.resolve();
  state.connectionPromise = openRealtime(initialText).finally(() => {
    state.connectionPromise = null;
  });
  return state.connectionPromise;
}

export async function openRealtime(initialText = "") {
  if (!realtimeEnabled || state.realtimeReady || state.rtcPeer) return;
  stopRecognition();
  state.conversationActive = true;
  touchConversationTimeout();
  setBusy(true, "أتصل بغروب…");
  const connectionStartedAt = performance.now();
  try {
    const supportedConstraints = navigator.mediaDevices.getSupportedConstraints?.() || {};
    const preferredId = getPreferredMicId();
    const buildConstraints = (withDevice) => {
      const c = {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      };
      if (supportedConstraints.sampleRate) c.sampleRate = { ideal: 48000 };
      if (supportedConstraints.sampleSize) c.sampleSize = { ideal: 16 };
      if (supportedConstraints.voiceIsolation) c.voiceIsolation = true;
      if (withDevice && preferredId) c.deviceId = { exact: preferredId };
      return c;
    };
    let stream;
    let audioConstraints = buildConstraints(true);
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints });
    } catch (error) {
      if (preferredId && ["NotFoundError", "OverconstrainedError", "NotReadableError"].includes(error.name)) {
        console.warn(`[Mic] preferred device ${preferredId.slice(0,8)} failed (${error.name}), retrying without deviceId`);
        audioConstraints = buildConstraints(false);
        stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints });
      } else {
        throw error;
      }
    }
    const microphoneTrack = stream.getAudioTracks()[0];
    if (microphoneTrack) {
      const s = microphoneTrack.getSettings();
      console.debug("[Mic] getSettings", {
        deviceId: s.deviceId ? s.deviceId.slice(0, 8) : "",
        echoCancellation: s.echoCancellation,
        noiseSuppression: s.noiseSuppression,
        autoGainControl: s.autoGainControl,
        voiceIsolation: s.voiceIsolation,
        sampleRate: s.sampleRate,
        channelCount: s.channelCount,
        sampleSize: s.sampleSize,
      });
      console.debug("[Mic] constraints applied", audioConstraints);
    }
    stream.getAudioTracks().forEach((track) => {
      track.addEventListener("ended", () => {
        if (!state.micAutoStartEnabled) return;
        if (state.rtcStream !== stream) return;
        console.warn("Microphone track ended unexpectedly, recovering");
        closeRealtime();
        state.conversationActive = false;
        updateControls();
        el.voiceStatus.textContent = "انقطع الميكروفون — نعيد المحاولة…";
        scheduleAutoRealtime(800);
      });
    });
    const pc = new RTCPeerConnection();
    const dc = pc.createDataChannel("oai-events");
    state.rtcPeer = pc;
    state.rtcChannel = dc;
    state.rtcStream = stream;
    stream.getAudioTracks().forEach((track) => pc.addTrack(track, stream));
    pc.ontrack = ({ streams }) => {
      ensureAssistantGain();
      resumeOutputContext();
      playback.srcObject = streams[0];
      playback.muted = false;
      playback.volume = 1;
      const gain = getOutputGain();
        if (gain) gain.gain.value = ASSISTANT_OUTPUT_GAIN;
      playback.play().catch((error) =>
        console.error("Realtime audio playback failed", error)
      );
    };
    dc.addEventListener("message", ({ data }) => {
      try { handleRealtimeEvent(JSON.parse(data)).catch((error) => console.error(error)); }
      catch (error) { console.error("Invalid Realtime event", error); }
    });
    const channelReady = new Promise((resolve, reject) => {
      dc.addEventListener("open", resolve, { once: true });
      dc.addEventListener("error", reject, { once: true });
    });
    pc.addEventListener("connectionstatechange", () => {
      if (!["failed", "closed"].includes(pc.connectionState)) return;
      if (state.rtcPeer !== pc) return;
      if (state.micAutoStartEnabled && realtimeEnabled) {
        console.warn(`Realtime connection ${pc.connectionState}, recovering with auto-mic`);
        const wasActive = state.conversationActive;
        closeRealtime();
        state.conversationActive = false;
        setBusy(false);
        updateControls();
        el.voiceStatus.textContent = "انقطع الاتصال الصوتي — نعيد المحاولة…";
        if (wasActive) scheduleAutoRealtime(1200);
        else scheduleAutoRealtime(1200);
      } else if (state.conversationActive) {
        endConversation(false);
      }
    });
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const realtimeHeaders = { "Content-Type": "application/sdp" };
    if (apiKey) realtimeHeaders["X-Kiosk-Key"] = apiKey;
    const response = await fetch("/api/v1/kiosk/realtime/session/", {
      method: "POST", headers: realtimeHeaders, body: offer.sdp,
    });
    if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
    state.localSessionId = response.headers.get("X-Local-Session-ID");
    state.currentStayId = response.headers.get("X-Stay-ID") || state.currentStayId;
    if (!state.localSessionId || !state.currentStayId) {
      throw new Error("Local Realtime session identity is missing");
    }
    const answerSdp = await response.text();
    await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
    await channelReady;
    console.debug(
      `Realtime connection latency: ${Math.round(performance.now() - connectionStartedAt)}ms`,
    );
    state.realtimeReady = true;
    state.realtimeRetryAttempts = 0;
    state.currentRequestId = uuid();
    state.toolIterations = 0;
    if (initialText.trim()) {
      const clean = initialText.trim();
      createMessage("user", clean, state.currentRequestId);
      await persistRealtimeMessage("user", clean, `typed-${state.currentRequestId}`, "voice");
      sendRealtime({
        type: "conversation.item.create",
        item: { type: "message", role: "user", content: [{ type: "input_text", text: clean }] },
      });
      sendRealtime({ type: "response.create" });
    } else {
      sendRealtime({
        type: "response.create",
        response: {
          instructions: "رحّب بالضيف الآن بجملة عربية قصيرة ودافئة جداً، ثم قل له: تفضل، أنا معك.",
        },
      });
    }
    cancelAutoStart();
    setBusy(false);
    updateControls();
    el.voiceStatus.textContent = "تفضل… أنا أستمع";
  } catch (error) {
    const errName = error && error.name ? error.name : "UnknownError";
    console.error(`Unable to start Realtime [${errName}]`, error);
    closeRealtime();
    state.conversationActive = false;
    setBusy(false);
    updateControls();
    if (state.micAutoStartEnabled && realtimeEnabled) {
      if (errName === "NotAllowedError") {
        state.micAutoStartEnabled = false;
        el.voiceStatus.textContent = "الميكروفون محظور — تحقق من إعدادات المتصفح (NotAllowedError)";
      } else if (errName === "NotFoundError") {
        el.voiceStatus.textContent = "لا يوجد ميكروفون (NotFoundError)";
      } else if (errName === "NotReadableError") {
        el.voiceStatus.textContent = "الميكروفون قيد الاستخدام (NotReadableError)";
      } else if (errName === "OverconstrainedError") {
        el.voiceStatus.textContent = `الميكروفون غير مدعوم (${errName}) — نعيد المحاولة…`;
      } else {
        el.voiceStatus.textContent = `تعذر تشغيل الميكروفون (${errName}) — نعيد المحاولة…`;
      }
      if (state.micAutoStartEnabled) {
        state.realtimeRetryAttempts += 1;
        if (state.realtimeRetryAttempts <= 5) {
          const backoff = Math.min(1800 * (2 ** (state.realtimeRetryAttempts - 1)), 15000);
          scheduleAutoRealtime(backoff + Math.floor(Math.random() * 500));
        }
      }
    } else {
      speakBrowser("تعذر تشغيل المحادثة المباشرة الآن. حاول مرة أخرى.", () => {
        scheduleWakeListener(500);
      }, true);
    }
  }
}

