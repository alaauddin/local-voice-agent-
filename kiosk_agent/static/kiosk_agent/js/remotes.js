"use strict";

import { el } from "./dom.js";
import { state } from "./state.js";
import { headers, patchJson, postJson, uuid } from "./api.js";

import { buildRemoteCard, icon } from "./remote-cards.js";

const AC_MODES = ["auto", "cool", "heat", "dry", "fan"];
const AC_FANS = ["auto", "low", "medium", "high"];
const remotePopupDialog = document.querySelector("#remotePopupDialog");
const remotePopupContent = document.querySelector("#remotePopupContent");
const closeRemotePopupButton = document.querySelector("#closeRemotePopup");
let expandedRemoteId = null;
let selectedLocation = "";
let remoteSyncComplete = false;
let remoteSyncInFlight = null;
let remoteSyncAttempts = 0;
let nextRemoteSyncAt = 0;

// A refresh should not close expanded options or drop keyboard focus.
function preservePresentation(container) {
  if (!container) return () => {};
  const openCards = new Set([...container.querySelectorAll(".dashboard-extra[open]")]
    .map(node => node.closest("[data-remote-id]")?.dataset.remoteId));
  const active = container.contains(document.activeElement) ? document.activeElement : null;
  const remoteId = active?.closest("[data-remote-id]")?.dataset.remoteId;
  const identity = active ? JSON.stringify(active.dataset) : null;
  return () => {
    container.querySelectorAll(".dashboard-extra").forEach(node => {
      node.open = openCards.has(node.closest("[data-remote-id]")?.dataset.remoteId);
    });
    if (!active || active.isConnected) return;
    const replacement = [...container.querySelectorAll("button, summary")].find(node =>
      node.tagName === active.tagName &&
      node.closest("[data-remote-id]")?.dataset.remoteId === remoteId &&
      JSON.stringify(node.dataset) === identity);
    replacement?.focus({ preventScroll: true });
  };
}

function setRemoteFeedback(message, kind = "") {
  if (!el.remoteFeedback) return;
  el.remoteFeedback.textContent = message || "";
  el.remoteFeedback.classList.toggle("is-error", kind === "error");
  el.remoteFeedback.classList.toggle("is-success", kind === "success");
}

function renderRemotePopup() {
  if (!remotePopupContent || !expandedRemoteId) return;
  const remote = state.remotes.find((item) => item.id === expandedRemoteId);
  if (!remote) {
    remotePopupDialog?.close();
    return;
  }
  const restore = preservePresentation(remotePopupContent);
  remotePopupContent.replaceChildren(buildRemoteCard(remote, true));
  restore();
}

function renderRemotes() {
  if (!el.remotesPanel || !el.voiceStage) return;
  const restore = preservePresentation(el.remotesPanel);
  el.remotesTrack.innerHTML = "";
  if (!state.remotes.length) {
    el.remotesPanel.hidden = true;
    if (el.workspaceTabs) el.workspaceTabs.hidden = true;
    el.voiceStage.classList.remove("has-remotes");
    return;
  }
  el.remotesPanel.hidden = false;
  if (el.workspaceTabs) el.workspaceTabs.hidden = false;
  if (el.remoteCount) el.remoteCount.textContent = String(state.remotes.length);
  el.remoteTitle.textContent = "أجهزة الشاليه";
  el.remoteLocation.textContent = `${state.remotes.length} أجهزة متاحة`;
  el.voiceStage.classList.add("has-remotes");
  const locations = [...new Set(state.remotes.map(remote => remote.location).filter(Boolean))];
  if (!locations.includes(selectedLocation)) selectedLocation = "";
  const filters = document.querySelector("#remoteFilters");
  if (filters) {
    filters.replaceChildren();
    ["", ...locations].forEach(location => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.location = location;
      button.textContent = location || "جميع الغرف";
      button.setAttribute("aria-pressed", String(location === selectedLocation));
      filters.append(button);
    });
  }
  state.remotes.filter(remote => !selectedLocation || remote.location === selectedLocation)
    .slice().sort((a, b) => Number(b.device_type === "ac") - Number(a.device_type === "ac"))
    .forEach(remote => el.remotesTrack.appendChild(buildRemoteCard(remote)));
  restore();
  if (remotePopupDialog?.open) renderRemotePopup();
}

function openRemotePopup(remote, sourceCard) {
  if (!remote || !sourceCard || !remotePopupDialog || !remotePopupContent) return;
  expandedRemoteId = remote.id;
  renderRemotePopup();
  const sourceRect = sourceCard.getBoundingClientRect();
  remotePopupDialog.showModal();
  const popupCard = remotePopupContent.querySelector(".remote-slide");
  const targetRect = popupCard.getBoundingClientRect();
  const scaleX = Math.max(.2, sourceRect.width / targetRect.width);
  const scaleY = Math.max(.2, sourceRect.height / targetRect.height);
  popupCard.animate(
    [
      {
        transform: `translate(${sourceRect.left - targetRect.left}px, ${sourceRect.top - targetRect.top}px) scale(${scaleX}, ${scaleY})`,
        opacity: .45,
      },
      { transform: "translate(0, 0) scale(1)", opacity: 1 },
    ],
    { duration: 420, easing: "cubic-bezier(.2,.82,.22,1)", fill: "both" },
  );
}

function closeRemotePopup() {
  if (!remotePopupDialog?.open) return;
  const popupCard = remotePopupContent.querySelector(".remote-slide");
  const sourceCard = el.remotesTrack.querySelector(
    `[data-remote-id="${expandedRemoteId}"]`,
  );
  if (!popupCard || !sourceCard) {
    remotePopupDialog.close();
    return;
  }
  const sourceRect = sourceCard.getBoundingClientRect();
  const targetRect = popupCard.getBoundingClientRect();
  const animation = popupCard.animate(
    [
      { transform: "translate(0, 0) scale(1)", opacity: 1 },
      {
        transform: `translate(${sourceRect.left - targetRect.left}px, ${sourceRect.top - targetRect.top}px) scale(${sourceRect.width / targetRect.width}, ${sourceRect.height / targetRect.height})`,
        opacity: .25,
      },
    ],
    { duration: 280, easing: "cubic-bezier(.4,0,.8,.2)", fill: "both" },
  );
  animation.finished.then(
    () => remotePopupDialog.close(),
    () => remotePopupDialog.close(),
  );
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

async function syncRemoteIps() {
  if (remoteSyncComplete || Date.now() < nextRemoteSyncAt) return;
  if (remoteSyncInFlight) return remoteSyncInFlight;
  remoteSyncInFlight = postJson("/api/v1/kiosk/remotes/sync/", {})
    .then((data) => {
      remoteSyncAttempts += 1;
      remoteSyncComplete = data.missing === 0 && data.ambiguous === 0;
      if (!remoteSyncComplete) {
        const retryDelay = remoteSyncAttempts < 6 ? 10000 : 60000;
        nextRemoteSyncAt = Date.now() + retryDelay;
      }
      return data;
    })
    .catch((error) => {
      remoteSyncAttempts += 1;
      const retryDelay = remoteSyncAttempts < 6 ? 10000 : 60000;
      nextRemoteSyncAt = Date.now() + retryDelay;
      // Discovery failure should not hide remotes that were already configured.
      console.debug("Failed to sync remote IPs", error);
    })
    .finally(() => {
      remoteSyncInFlight = null;
    });
  return remoteSyncInFlight;
}

async function syncAndLoadRemotes() {
  await syncRemoteIps();
  await loadRemotes();
}

function startRemotesRefresh() {
  window.setInterval(async () => {
    if (document.hidden || state.remotePressing) return;
    await syncRemoteIps();
    await loadRemotes();
  }, 10000);
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
  node.setAttribute("aria-busy", "true");
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
    node.removeAttribute("aria-busy");
    state.remotePressing = false;
  }
}

function nextValue(values, current) {
  const index = values.indexOf(current);
  return values[(index + 1) % values.length];
}

function acChangeFor(remote, node) {
  const current = remote.ac_state;
  const field = node.dataset.field;
  const action = node.dataset.action;
  if (!current || !(field in current)) return null;
  if (action === "toggle") return { [field]: !current[field] };
  if (field === "temperature") {
    const difference = action === "increase" ? 1 : -1;
    const capabilities = remote.ac_capabilities || {};
    const minimum = capabilities.temperature_min ?? 16;
    const maximum = capabilities.temperature_max ?? 32;
    return { temperature: Math.min(maximum, Math.max(minimum, current.temperature + difference)) };
  }
  if (field === "mode") return { mode: nextValue(AC_MODES, current.mode) };
  if (field === "fan") return { fan: nextValue(AC_FANS, current.fan) };
  return null;
}

async function updateACState(remote, node) {
  if (!remote || state.remotePressing) return;
  const changes = acChangeFor(remote, node);
  if (!changes) return;
  state.remotePressing = true;
  node.classList.add("sending");
  node.setAttribute("aria-busy", "true");
  setRemoteFeedback("جاري إرسال أمر المكيف…");
  try {
    const data = await patchJson(`/api/v1/kiosk/devices/${remote.id}/ac-state/`, {
      ...changes,
      request_id: uuid(),
    });
    remote.ac_state = {
      ...remote.ac_state,
      ...data.state,
      state_version: data.state_version,
      updated_at: data.updated_at,
    };
    renderRemotes();
    setRemoteFeedback("تم تحديث حالة المكيف", "success");
  } catch (error) {
    node.classList.add("error");
    setRemoteFeedback(error.message || "فشل إرسال أمر المكيف", "error");
    window.setTimeout(() => node.classList.remove("error"), 1400);
  } finally {
    node.classList.remove("sending");
    node.removeAttribute("aria-busy");
    state.remotePressing = false;
  }
}

async function sendLGTVCommand(remote, node) {
  if (!remote || !node.dataset.lgCommand) return;
  node.classList.add("sending");
  node.setAttribute("aria-busy", "true");
  try {
    const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
    const response = await fetch("/api/tv-remote/command/", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify({
        remote_id: remote.id,
        command: node.dataset.lgCommand,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success !== true) {
      throw new Error(data.error || "تعذر إرسال أمر التلفاز");
    }
    setRemoteFeedback("");
  } catch (error) {
    node.classList.add("error");
    setRemoteFeedback(error.message || "تعذر الاتصال بريموت التلفاز", "error");
    window.setTimeout(() => node.classList.remove("error"), 1400);
  } finally {
    node.classList.remove("sending");
    node.removeAttribute("aria-busy");
  }
}

function bindRemotesUi() {
  if (!el.remotesPanel) return;
  document.querySelector("#remoteFilters")?.addEventListener("click", event => {
    const button = event.target.closest("button[data-location]");
    if (!button) return;
    selectedLocation = button.dataset.location;
    renderRemotes();
  });
  document.querySelectorAll("[data-remote-view]").forEach(button => {
    button.addEventListener("click", () => {
      el.remotesTrack.dataset.view = button.dataset.remoteView;
      document.querySelectorAll("[data-remote-view]").forEach(item => {
        item.setAttribute("aria-pressed", String(item === button));
      });
    });
  });
  document.querySelectorAll("[data-dashboard-icon]").forEach(node => {
    node.replaceChildren(icon(node.dataset.dashboardIcon));
  });
  document.querySelectorAll(".dashboard-header-nav a").forEach(link => {
    link.addEventListener("click", () => {
      document.querySelectorAll(".dashboard-header-nav a").forEach(item => {
        item.classList.toggle("is-current", item === link);
      });
    });
  });
  el.workspaceTabs?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-workspace]");
    if (!button) return;
    const view = button.dataset.workspace;
    el.voiceStage.dataset.mobileView = view;
    el.workspaceTabs.querySelectorAll("button").forEach((item) => {
      const active = item === button;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
  });
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

  const handleRemoteInteraction = (event, container) => {
    const openButton = event.target.closest("[data-open-remote]");
    if (openButton && container.contains(openButton)) {
      event.preventDefault();
      const remote = state.remotes.find(
        (item) => item.id === Number(openButton.dataset.openRemote),
      );
      openRemotePopup(remote, openButton.closest(".remote-slide"));
      return;
    }
    const acNode = event.target.closest(".ac-control");
    if (acNode && !acNode.disabled && container.contains(acNode)) {
      event.preventDefault();
      const controls = acNode.closest(".ac-controls");
      const remote = state.remotes.find((item) => item.id === Number(controls?.dataset.deviceId));
      updateACState(remote, acNode);
      return;
    }
    const lgNode = event.target.closest(".lg-tv-control");
    if (lgNode && container.contains(lgNode)) {
      event.preventDefault();
      const controls = lgNode.closest(".lg-tv-remote");
      const remote = state.remotes.find((item) => item.id === Number(controls?.dataset.deviceId));
      sendLGTVCommand(remote, lgNode);
      return;
    }
    const node = event.target.closest(".remote-button");
    if (!node || node.disabled || !container.contains(node)) return;
    event.preventDefault();
    const button = findRemoteButton(Number(node.dataset.buttonId));
    handleRemoteButtonClick(button, node);
  };

  // Delegate clicks so controls work after card and popup re-renders.
  el.remotesTrack.addEventListener("click", (event) => {
    handleRemoteInteraction(event, el.remotesTrack);
  });
  remotePopupContent?.addEventListener("click", (event) => {
    handleRemoteInteraction(event, remotePopupContent);
  });
  closeRemotePopupButton?.addEventListener("click", closeRemotePopup);
  remotePopupDialog?.addEventListener("click", (event) => {
    if (event.target === remotePopupDialog) closeRemotePopup();
  });
  remotePopupDialog?.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeRemotePopup();
  });
  remotePopupDialog?.addEventListener("close", () => {
    expandedRemoteId = null;
    remotePopupContent.replaceChildren();
  });

}

export { loadRemotes, syncAndLoadRemotes, bindRemotesUi, renderRemotes, startRemotesRefresh };
