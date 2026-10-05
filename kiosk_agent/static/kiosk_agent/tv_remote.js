"use strict";

const controls = document.querySelector("#remoteControls");
const feedback = document.querySelector("#remoteFeedback");
const statusIndicator = document.querySelector("#remoteStatus");
const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]").value;
const remoteId = controls.dataset.remoteId;
let feedbackTimer = null;

function setOnline(online, checking = false) {
  statusIndicator.className = `remote-status ${checking ? "is-checking" : online ? "is-online" : "is-offline"}`;
  statusIndicator.querySelector("b").textContent = checking
    ? "جارٍ التحقق…"
    : online ? "ريموت التلفاز متصل" : "ريموت التلفاز غير متصل";
}

function showError(message) {
  window.clearTimeout(feedbackTimer);
  feedback.textContent = message || "تعذّر الاتصال بريموت التلفاز";
  feedbackTimer = window.setTimeout(() => { feedback.textContent = ""; }, 5000);
}

async function refreshStatus(showChecking = false) {
  if (!remoteId) {
    setOnline(false);
    return;
  }
  if (showChecking) setOnline(false, true);
  try {
    const response = await fetch(`/api/tv-remote/status/?remote_id=${encodeURIComponent(remoteId)}`, {
      headers: { "Accept": "application/json" },
      credentials: "same-origin",
    });
    const data = await response.json().catch(() => ({}));
    setOnline(response.ok && data.online === true);
  } catch (_error) {
    setOnline(false);
  }
}

async function sendCommand(button) {
  button.classList.add("is-sending");
  try {
    const response = await fetch("/api/tv-remote/command/", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify({ remote_id: remoteId, command: button.dataset.command }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success !== true) {
      setOnline(false);
      showError(data.error);
      return;
    }
    feedback.textContent = "";
    setOnline(true);
  } catch (_error) {
    setOnline(false);
    showError();
  } finally {
    button.classList.remove("is-sending");
  }
}

controls.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-command]");
  if (button) sendCommand(button);
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshStatus();
});

refreshStatus(true);
window.setInterval(() => { if (!document.hidden) refreshStatus(); }, 30000);
