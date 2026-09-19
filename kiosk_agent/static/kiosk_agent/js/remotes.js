"use strict";

import { el } from "./dom.js";
import { state } from "./state.js";
import { headers, postJson } from "./api.js";

const REMOTE_ICONS = {
  power: "⏻",
  plus: "＋",
  minus: "−",
  mode: "⟳",
  fan: "✧",
  light: "✦",
};

function remoteIcon(name) {
  return REMOTE_ICONS[name] || "•";
}

function setRemoteFeedback(message, kind = "") {
  if (!el.remoteFeedback) return;
  el.remoteFeedback.textContent = message || "";
  el.remoteFeedback.classList.toggle("is-error", kind === "error");
  el.remoteFeedback.classList.toggle("is-success", kind === "success");
}

function updateRemoteChrome() {
  const remote = state.remotes[state.remoteIndex];
  if (!remote) return;
  el.remoteTitle.textContent = remote.name;
  el.remoteLocation.textContent = remote.location || "";
  el.remotesTrack.style.transform = `translateX(-${state.remoteIndex * 100}%)`;
  el.remoteDots.querySelectorAll("button").forEach((dot, index) => {
    dot.classList.toggle("active", index === state.remoteIndex);
  });
  const atStart = state.remoteIndex <= 0;
  const atEnd = state.remoteIndex >= state.remotes.length - 1;
  el.remotePrev.disabled = atStart;
  el.remoteNext.disabled = atEnd;
}

function goToRemote(index) {
  if (!state.remotes.length) return;
  state.remoteIndex = Math.max(0, Math.min(state.remotes.length - 1, index));
  updateRemoteChrome();
}

function buildRemoteGrid(remote) {
  const maxRow = remote.buttons.reduce((max, button) => Math.max(max, button.row), 0);
  const maxCol = remote.buttons.reduce((max, button) => Math.max(max, button.column), 0);
  const grid = document.createElement("div");
  grid.className = "remote-grid";
  grid.style.gridTemplateColumns = `repeat(${maxCol + 1}, minmax(0, 1fr))`;
  remote.buttons
    .slice()
    .sort((a, b) => a.sort_order - b.sort_order || a.row - b.row || a.column - b.column)
    .forEach((button) => {
      const node = document.createElement("button");
      node.type = "button";
      node.className = "remote-button";
      node.style.gridRow = String(button.row + 1);
      node.style.gridColumn = String(button.column + 1);
      node.dataset.buttonId = String(button.id);
      node.disabled = !button.configured;
      node.title = button.configured ? button.label : "غير مهيأ بعد";
      node.innerHTML = `<span class="icon">${remoteIcon(button.icon)}</span><span>${button.label}</span>`;
      grid.appendChild(node);
    });
  return grid;
}

function renderRemotes() {
  if (!el.remotesPanel || !el.voiceStage) return;
  el.remotesTrack.innerHTML = "";
  el.remoteDots.innerHTML = "";
  if (!state.remotes.length) {
    el.remotesPanel.hidden = true;
    el.voiceStage.classList.remove("has-remotes");
    return;
  }
  el.remotesPanel.hidden = false;
  el.voiceStage.classList.add("has-remotes");
  state.remotes.forEach((remote, index) => {
    const slide = document.createElement("div");
    slide.className = "remote-slide";
    slide.appendChild(buildRemoteGrid(remote));
    el.remotesTrack.appendChild(slide);
    const dot = document.createElement("button");
    dot.type = "button";
    dot.setAttribute("aria-label", remote.name);
    dot.addEventListener("click", () => goToRemote(index));
    el.remoteDots.appendChild(dot);
  });
  if (state.remoteIndex >= state.remotes.length) state.remoteIndex = 0;
  updateRemoteChrome();
}

function findRemoteButton(buttonId) {
  for (const remote of state.remotes) {
    const button = remote.buttons.find((item) => item.id === buttonId);
    if (button) return button;
  }
  return null;
}

async function loadRemotes() {
  if (!el.remotesPanel) return;
  try {
    const response = await fetch("/api/v1/kiosk/remotes/", { headers: headers() });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "remotes_failed");
    state.remotes = Array.isArray(data.remotes) ? data.remotes : [];
    renderRemotes();
  } catch (error) {
    console.debug("Failed to load remotes", error);
    state.remotes = [];
    renderRemotes();
  }
}

function handleRemoteButtonClick(button, node) {
  if (!button || !button.configured || state.remotePressing) return;
  if (button.requires_confirmation) {
    state.pendingRemoteButton = { button, node };
    el.remoteConfirmTitle.textContent = button.label;
    el.remoteConfirmText.textContent = `هل تريد تنفيذ «${button.label}»؟`;
    el.remoteConfirmDialog.showModal();
    return;
  }
  pressRemoteButton(button, node);
}

async function pressRemoteButton(button, node) {
  if (state.remotePressing) return;
  state.remotePressing = true;
  node.classList.add("sending");
  node.classList.remove("success", "error");
  setRemoteFeedback("جاري الإرسال…");
  try {
    const data = await postJson(`/api/v1/kiosk/remote-buttons/${button.id}/press/`, {});
    node.classList.add("success");
    setRemoteFeedback(data.label ? `تم: ${data.label}` : "تم التنفيذ", "success");
    window.setTimeout(() => node.classList.remove("success"), 1200);
  } catch (error) {
    node.classList.add("error");
    setRemoteFeedback(error.message || "فشل التنفيذ", "error");
    window.setTimeout(() => node.classList.remove("error"), 1400);
  } finally {
    node.classList.remove("sending");
    state.remotePressing = false;
  }
}

function bindRemotesUi() {
  if (!el.remotesPanel) return;
  el.remotePrev.addEventListener("click", () => goToRemote(state.remoteIndex - 1));
  el.remoteNext.addEventListener("click", () => goToRemote(state.remoteIndex + 1));
  el.cancelRemoteConfirm.addEventListener("click", () => {
    state.pendingRemoteButton = null;
    el.remoteConfirmDialog.close();
  });
  el.confirmRemotePress.addEventListener("click", () => {
    const pending = state.pendingRemoteButton;
    el.remoteConfirmDialog.close();
    state.pendingRemoteButton = null;
    if (pending) pressRemoteButton(pending.button, pending.node);
  });

  // Delegate clicks so presses work even after re-renders / swipe gestures.
  el.remotesTrack.addEventListener("click", (event) => {
    const node = event.target.closest(".remote-button");
    if (!node || node.disabled || !el.remotesTrack.contains(node)) return;
    event.preventDefault();
    const button = findRemoteButton(Number(node.dataset.buttonId));
    handleRemoteButtonClick(button, node);
  });

  let startX = 0;
  let dragging = false;
  el.remotesCarousel.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    // Never capture pointers that start on a remote button — that blocks click.
    if (event.target.closest(".remote-button, .remotes-nav button, .remote-dots button")) {
      dragging = false;
      return;
    }
    dragging = true;
    startX = event.clientX;
  });
  el.remotesCarousel.addEventListener("pointerup", (event) => {
    if (!dragging) return;
    dragging = false;
    const delta = event.clientX - startX;
    if (Math.abs(delta) < 40) return;
    if (delta < 0) goToRemote(state.remoteIndex + 1);
    else goToRemote(state.remoteIndex - 1);
  });
  el.remotesCarousel.addEventListener("pointercancel", () => {
    dragging = false;
  });
  el.remotesCarousel.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") goToRemote(state.remoteIndex - 1);
    if (event.key === "ArrowRight") goToRemote(state.remoteIndex + 1);
  });
}

export { loadRemotes, bindRemotesUi, renderRemotes };
