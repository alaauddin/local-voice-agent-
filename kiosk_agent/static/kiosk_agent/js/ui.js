"use strict";

import { el } from "./dom.js";
import { state } from "./state.js";
import { realtimeEnabled } from "./config.js";
import { headers } from "./api.js";
import { stopRecognition, scheduleWakeListener } from "./voice.js";
import { startRealtime } from "./realtime.js";

export const avatarObjectUrls = [];

export function setAvatar(mode, force = false) {
  const videoMode = ["thinking", "speaking"].includes(mode) ? mode : "idle";
  if (!force && el.avatar.dataset.state === videoMode) return;
  el.avatar.dataset.state = videoMode;
  el.avatar.querySelectorAll(".avatar-video").forEach((video) => {
    const active = video.dataset.avatarState === videoMode;
    video.classList.toggle("active", active);
    if (active) {
      if (video.src && !document.hidden) video.play().catch(() => {});
    } else {
      video.pause();
    }
  });
}

export function preloadAvatarVideos() {
  el.avatar.querySelectorAll(".avatar-video[data-src]").forEach(async (video) => {
    try {
      const response = await fetch(video.dataset.src, { cache: "force-cache" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const objectUrl = URL.createObjectURL(await response.blob());
      avatarObjectUrls.push(objectUrl);
      video.src = objectUrl;
      video.load();
      if (video.dataset.avatarState === el.avatar.dataset.state && !document.hidden) {
        video.play().catch(() => {});
      }
    } catch (error) {
      console.warn("Avatar video could not be preloaded", error);
    }
  });
}

export function updateControls() {
  el.send.disabled = !state.connected || (!realtimeEnabled && state.busy) || !el.input.value.trim();
  el.mic.disabled = !state.connected
    || (!realtimeEnabled && state.busy)
    || (!realtimeEnabled && !state.recognition);
  el.mic.classList.toggle("wake-armed", state.wakeArmed && state.recognitionMode === "wake");
  el.mic.classList.toggle("listening", state.recognitionMode === "command" && state.recognizing);
  el.mic.classList.toggle("conversation-active", state.conversationActive);
}

export function cancelAutoStart() {
  if (state.autoStartTimer) {
    clearTimeout(state.autoStartTimer);
    state.autoStartTimer = null;
  }
}

export function scheduleAutoRealtime(delay = 1200) {
  if (!realtimeEnabled || !state.micAutoStartEnabled) return;
  if (state.realtimeReady || state.rtcPeer) return;
  if (!state.connected) return;
  if (state.autoStartTimer) return;
  state.autoStartTimer = window.setTimeout(() => {
    state.autoStartTimer = null;
    if (!state.micAutoStartEnabled || !state.connected || state.realtimeReady || state.rtcPeer) return;
    autoRealtimeStartup();
  }, delay);
}

export async function autoRealtimeStartup() {
  if (!realtimeEnabled || !state.micAutoStartEnabled) return;
  if (state.realtimeReady || state.rtcPeer) return;
  if (!state.connected) return;
  await startRealtime();
  if (!state.realtimeReady && state.micAutoStartEnabled && !state.rtcPeer && state.connected) {
    scheduleAutoRealtime(1500);
  }
}

export function setConnection(mode, text) {
  state.connected = mode === "online";
  el.connectionPill.classList.toggle("online", mode === "online");
  el.connectionPill.classList.toggle("offline", mode === "offline");
  el.mobileStatus.classList.toggle("online", mode === "online");
  el.connectionText.textContent = text;
  updateControls();
  if (state.connected && state.wakeArmed && !state.recognizing) scheduleWakeListener();
  if (state.connected && realtimeEnabled && state.micAutoStartEnabled && !state.realtimeReady && !state.rtcPeer) {
    scheduleAutoRealtime(700);
  }
}

export function setBusy(busy, text = "يجهّز لك الرد…") {
  state.busy = busy;
  el.activity.hidden = !busy;
  el.activityText.textContent = text;
  el.input.disabled = busy && !realtimeEnabled;
  if (busy) {
    stopRecognition();
    setAvatar("thinking");
    el.voiceStatus.textContent = text;
  }
  updateControls();
}

export function scrollBottom() {
  requestAnimationFrame(() => { el.messages.scrollTop = el.messages.scrollHeight; });
}

export function setMessagesOpen(open) {
  state.messagesOpen = open;
  el.messagesDrawer.classList.toggle("open", open);
  el.messagesDrawer.setAttribute("aria-hidden", String(!open));
  el.messagesToggle.setAttribute("aria-expanded", String(open));
  if (open) {
    state.unreadMessages = 0;
    el.messageCount.hidden = true;
    scrollBottom();
    el.closeMessages.focus();
  } else {
    el.messagesToggle.focus();
  }
}
el.messagesDrawer?.addEventListener("keydown", (e) => {
  if (!state.messagesOpen || e.key !== "Tab") return;
  const focusable = [...el.messagesDrawer.querySelectorAll('button, [href], textarea, select, [tabindex]:not([tabindex="-1"])')].filter(x=>x.offsetParent!==null);
  if (!focusable.length) return;
  const first = focusable[0], last = focusable[focusable.length-1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
});

export function noteNewMessage() {
  if (state.messagesOpen || state.loadingMemory) return;
  state.unreadMessages += 1;
  el.messageCount.textContent = String(Math.min(state.unreadMessages, 99));
  el.messageCount.hidden = false;
}

export function createMessage(role, content = "", requestId = "") {
  const row = document.createElement("article");
  row.className = `message-row ${role}`;
  if (requestId) row.dataset.requestId = requestId;
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.dir = "auto";
  if (role === "assistant") {
    const label = document.createElement("span");
    label.className = "message-label";
    label.textContent = state.persona;
    const body = document.createElement("span");
    body.className = "message-content";
    body.textContent = content;
    bubble.append(label, body);
  } else {
    bubble.textContent = content;
  }
  row.append(bubble);
  el.messages.append(row);
  const rows = el.messages.querySelectorAll(".message-row");
  if (rows.length > 200) rows[0].remove();
  noteNewMessage();
  scrollBottom();
  return role === "assistant" ? bubble.querySelector(".message-content") : bubble;
}

export function streamFor(requestId) {
  if (!state.streams.has(requestId)) state.streams.set(requestId, createMessage("assistant", "", requestId));
  return state.streams.get(requestId);
}

export async function loadMemory() {
  try {
    const response = await fetch("/api/v1/kiosk/messages/", { headers: headers() });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.persona = data.chalet.persona_name || "غروب";
    state.currentStayId = data.stay_id;
    el.chaletName.textContent = data.chalet.chalet_name || "الشاليه";
    el.personaIntro.textContent = `مرحباً بك، أنا ${state.persona}، كونسيرجك الرقمي الخاص.`;
    el.mobilePersona.textContent = state.persona;
    if (data.chalet.welcome_message) el.welcomeMessage.textContent = data.chalet.welcome_message;
    state.loadingMemory = true;
    data.messages.forEach((message) => {
      const bubble = createMessage(message.role, message.content, message.request_id);
      bubble.closest(".message-row").dataset.messageId = String(message.id);
      bubble.closest(".message-row").dataset.persisted = "true";
    });
    state.loadingMemory = false;
    if (data.messages.some((message) => message.role === "user" && ["queued", "streaming"].includes(message.status))) {
      setBusy(true, "جارٍ استكمال طلبك…");
    }
  } catch (error) {
    console.error("Unable to load kiosk memory", error);
  }
}

