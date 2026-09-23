"use strict";

import { el } from "./dom.js";
import { state } from "./state.js";
import { apiKey, realtimeEnabled } from "./config.js";
import {
  createMessage, streamFor, setBusy, scrollBottom, setConnection, scheduleAutoRealtime,
} from "./ui.js";
import { resetAudio, receiveChunk, finishAudio } from "./tts.js";
import { closeRealtime } from "./realtime.js";
import { finishTurn } from "./conversation.js";

export function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const key = apiKey ? `?key=${encodeURIComponent(apiKey)}` : "";
  state.socket = new WebSocket(`${protocol}://${location.host}/ws/kiosk/${key}`);
  setConnection("connecting", "جاري الاتصال…");
  state.socket.addEventListener("open", () => {
    state.reconnectAttempts = 0;
    setConnection("online", "متصل وجاهز لخدمتك");
    if (realtimeEnabled && state.micAutoStartEnabled) scheduleAutoRealtime(600);
  });
  state.socket.addEventListener("message", ({ data }) => {
    try { handleEvent(JSON.parse(data)); } catch (error) { console.error("Invalid socket event", error); }
  });
  state.socket.addEventListener("close", () => {
    setConnection("offline", "انقطع الاتصال — نحاول مجدداً");
    if (state.shouldReconnect) {
      const delay = Math.min(1000 * (2 ** state.reconnectAttempts++), 10000);
      window.setTimeout(connect, delay);
    }
  });
  state.socket.addEventListener("error", () => state.socket.close());
}

export function handleEvent(event) {
  const requestId = event.request_id || "current";
  switch (event.event) {
    case "accepted": setBusy(true); break;
    case "status": setBusy(true, event.status === "thinking" ? "يفكر في أفضل طريقة لخدمتك…" : "يجهّز لك الرد…"); break;
    case "token":
      streamFor(requestId).textContent += event.token;
      scrollBottom();
      break;
    case "tool_status": setBusy(true, event.status === "running" ? "يرتّب طلبك الآن…" : "تم ترتيب الطلب…"); break;
    case "complete": {
      const target = streamFor(requestId);
      if (!target.textContent) target.textContent = event.content || "تمت خدمتك بكل سرور.";
      state.streams.delete(requestId);
      setBusy(true, "يحضّر الرد الصوتي…");
      clearTimeout(state.completionTimer);
      state.completionTimer = window.setTimeout(finishTurn, 4000);
      break;
    }
    case "tts_status":
      clearTimeout(state.completionTimer);
      resetAudio(event.nonce, event.total);
      setBusy(true, "يحضّر الرد الصوتي…");
      break;
    case "tts_audio": receiveChunk(event); break;
    case "tts_chunk_fallback": receiveChunk({ ...event, fallbackText: event.text }); break;
    case "tts_fallback":
      resetAudio(event.nonce, 1);
      receiveChunk({ ...event, seq: 0, total: 1, fallbackText: event.text });
      finishAudio({ ...event, total: 1 });
      break;
    case "tts_end": finishAudio(event); break;
    case "busy": setBusy(true, event.message || "يوجد طلب قيد التنفيذ…"); break;
    case "message_persisted": {
      if (event.stay_id && state.currentStayId && event.stay_id !== state.currentStayId) break;
      let row = [...el.messages.querySelectorAll(".message-row")]
        .find((item) => item.dataset.messageId === String(event.message_id));
      if (!row) {
        row = [...el.messages.querySelectorAll(".message-row")]
          .find((item) => item.dataset.requestId === requestId
            && item.classList.contains(event.role) && item.dataset.persisted !== "true");
      }
      if (!row) {
        const bubble = createMessage(event.role, event.content || "", requestId);
        row = bubble.closest(".message-row");
      }
      if (row) {
        const content = row.querySelector(".message-content") || row.querySelector(".message-bubble");
        if (content) content.textContent = event.content || "";
        row.dataset.messageId = String(event.message_id || "");
        row.dataset.sequence = String(event.sequence || "");
        row.dataset.persisted = "true";
      }
      break;
    }
    case "error":
      createMessage("assistant", event.message || "تعذر إكمال الطلب حالياً. يرجى المحاولة مرة أخرى.");
      finishTurn();
      break;
    case "cancelled": finishTurn(); break;
    case "reset":
      closeRealtime();
      state.localSessionId = null;
      state.currentStayId = event.new_stay_id || null;
      state.conversationActive = false;
      restartSocket();
      break;
    default: break;
  }
}

export function restartSocket() {
  state.shouldReconnect = false;
  if (state.socket) state.socket.close();
  window.setTimeout(() => { state.shouldReconnect = true; connect(); }, 150);
}
