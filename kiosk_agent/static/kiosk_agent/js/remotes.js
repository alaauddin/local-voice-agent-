"use strict";

import { el } from "./dom.js";
import { state } from "./state.js";
import { headers, patchJson, postJson, uuid } from "./api.js";

const REMOTE_ICONS = {
  power: "⏻",
  plus: "＋",
  minus: "−",
  mode: "⟳",
  fan: "≋",
  light: "✦",
  up: "⌃",
  down: "⌄",
  left: "‹",
  right: "›",
  play: "▶",
  pause: "Ⅱ",
  menu: "MENU",
  volume: "◖",
};

const AC_MODE_LABELS = {
  auto: "تلقائي",
  cool: "تبريد",
  heat: "تدفئة",
  dry: "تجفيف",
  fan: "مروحة",
};

const AC_FAN_LABELS = {
  auto: "تلقائية",
  low: "منخفضة",
  medium: "متوسطة",
  high: "عالية",
};

const AC_FEATURE_LABELS = {
  swing_vertical: "تأرجح رأسي",
  swing_horizontal: "تأرجح أفقي",
  turbo: "توربو",
  sleep: "نوم",
  eco: "اقتصادي",
  quiet: "هادئ",
  light: "إضاءة",
  x_fan: "X-Fan",
};

const AC_MODES = Object.keys(AC_MODE_LABELS);
const AC_FANS = Object.keys(AC_FAN_LABELS);
const remotePopupDialog = document.querySelector("#remotePopupDialog");
const remotePopupContent = document.querySelector("#remotePopupContent");
const closeRemotePopupButton = document.querySelector("#closeRemotePopup");
let expandedRemoteId = null;

function remoteIcon(name) {
  return REMOTE_ICONS[name] || "•";
}

function setRemoteFeedback(message, kind = "") {
  if (!el.remoteFeedback) return;
  el.remoteFeedback.textContent = message || "";
  el.remoteFeedback.classList.toggle("is-error", kind === "error");
  el.remoteFeedback.classList.toggle("is-success", kind === "success");
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
      node.dataset.key = button.key;
      node.dataset.icon = button.icon || "";
      node.disabled = !button.configured;
      node.title = button.configured ? button.label : "غير مهيأ بعد";
      node.setAttribute("aria-label", button.label);
      const icon = document.createElement("span");
      icon.className = "icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = remoteIcon(button.icon);
      const label = document.createElement("span");
      label.className = "remote-button-label";
      label.textContent = button.label;
      node.append(icon, label);
      grid.appendChild(node);
    });
  return grid;
}

function stateItem(label, value) {
  const item = document.createElement("div");
  item.className = "ac-state-item";
  const name = document.createElement("small");
  name.textContent = label;
  const current = document.createElement("strong");
  current.textContent = value;
  item.append(name, current);
  return item;
}

function acControl(label, field, options = {}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `ac-control ${options.className || ""}`.trim();
  button.dataset.field = field;
  if (options.action) button.dataset.action = options.action;
  button.textContent = label;
  button.setAttribute("aria-label", options.ariaLabel || label);
  button.classList.toggle("is-active", Boolean(options.active));
  return button;
}

function buildACControls(remote) {
  const current = remote.ac_state;
  const controls = document.createElement("div");
  controls.className = "ac-controls";
  controls.dataset.deviceId = String(remote.id);

  const primary = document.createElement("div");
  primary.className = "ac-primary-controls";
  primary.append(
    acControl(current.power ? "إيقاف" : "تشغيل", "power", {
      action: "toggle",
      active: current.power,
      className: "ac-control-power",
      ariaLabel: current.power ? "إيقاف المكيف" : "تشغيل المكيف",
    }),
    acControl("−", "temperature", { action: "decrease", ariaLabel: "خفض درجة الحرارة" }),
    acControl("+", "temperature", { action: "increase", ariaLabel: "رفع درجة الحرارة" }),
  );

  const cycles = document.createElement("div");
  cycles.className = "ac-cycle-controls";
  cycles.append(
    acControl(`الوضع: ${AC_MODE_LABELS[current.mode] || current.mode}`, "mode", {
      action: "cycle",
    }),
    acControl(`المروحة: ${AC_FAN_LABELS[current.fan] || current.fan}`, "fan", {
      action: "cycle",
    }),
  );

  const features = document.createElement("div");
  features.className = "ac-feature-controls";
  Object.entries(AC_FEATURE_LABELS).forEach(([field, label]) => {
    features.appendChild(acControl(label, field, {
      action: "toggle",
      active: current[field],
    }));
  });

  controls.append(primary, cycles, features);
  return controls;
}

function buildACState(remote) {
  const state = remote.ac_state;
  const panel = document.createElement("div");
  panel.className = "ac-state";
  if (!state) {
    panel.classList.add("is-unavailable");
    panel.textContent = "حالة المكيف غير متاحة";
    return panel;
  }

  const summary = document.createElement("div");
  summary.className = "ac-state-summary";
  const power = document.createElement("span");
  power.className = `ac-power ${state.power ? "is-on" : "is-off"}`;
  power.textContent = state.power ? "يعمل" : "متوقف";
  const temperature = document.createElement("strong");
  temperature.className = "ac-temperature";
  temperature.textContent = `${state.temperature}°`;
  summary.append(power, temperature);

  const details = document.createElement("div");
  details.className = "ac-state-details";
  details.append(
    stateItem("الوضع", AC_MODE_LABELS[state.mode] || state.mode),
    stateItem("المروحة", AC_FAN_LABELS[state.fan] || state.fan),
  );

  const features = document.createElement("div");
  features.className = "ac-features";
  Object.entries(AC_FEATURE_LABELS).forEach(([key, label]) => {
    if (!state[key]) return;
    const feature = document.createElement("span");
    feature.textContent = label;
    features.appendChild(feature);
  });

  panel.append(summary, details);
  if (features.childElementCount) panel.appendChild(features);
  panel.appendChild(buildACControls(remote));
  return panel;
}

function buildRemoteCard(remote, expanded = false) {
  const slide = document.createElement("article");
  slide.className = "remote-slide";
  slide.dataset.remoteId = String(remote.id);
  slide.classList.toggle("is-expanded", expanded);
  const heading = document.createElement("div");
  heading.className = "remote-slide-heading";
  const copy = document.createElement("div");
  const name = document.createElement("strong");
  name.textContent = remote.name;
  const location = document.createElement("small");
  location.textContent =
    [remote.location, remote.device_name].filter(Boolean).join(" · ") || "داخل الشاليه";
  copy.append(name, location);
  const isAC = remote.device_type === "ac";
  const configuredCount = remote.buttons.filter((button) => button.configured).length;
  const headingActions = document.createElement("div");
  headingActions.className = "remote-heading-actions";
  const count = document.createElement("span");
  count.className = "remote-kind-badge";
  count.textContent = isAC
    ? (remote.brand_label || remote.brand || "مكيف")
    : `${configuredCount} أوامر`;
  headingActions.appendChild(count);
  if (!expanded) {
    const open = document.createElement("button");
    open.type = "button";
    open.className = "remote-open-button";
    open.dataset.openRemote = String(remote.id);
    open.textContent = "فتح";
    open.setAttribute("aria-label", `فتح جهاز التحكم ${remote.name}`);
    headingActions.appendChild(open);
  }
  heading.append(copy, headingActions);
  slide.classList.toggle("ac-remote-slide", isAC);
  slide.append(heading, isAC ? buildACState(remote) : buildRemoteGrid(remote));
  return slide;
}

function renderRemotePopup() {
  if (!remotePopupContent || !expandedRemoteId) return;
  const remote = state.remotes.find((item) => item.id === expandedRemoteId);
  if (!remote) {
    remotePopupDialog?.close();
    return;
  }
  remotePopupContent.replaceChildren(buildRemoteCard(remote, true));
}

function renderRemotes() {
  if (!el.remotesPanel || !el.voiceStage) return;
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
  state.remotes.forEach((remote) => el.remotesTrack.appendChild(buildRemoteCard(remote)));
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

function startRemotesRefresh() {
  window.setInterval(() => {
    if (!document.hidden && !state.remotePressing) loadRemotes();
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
    return { temperature: Math.min(32, Math.max(16, current.temperature + difference)) };
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

function bindRemotesUi() {
  if (!el.remotesPanel) return;
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
    const openButton = event.target.closest(".remote-open-button");
    if (openButton && container.contains(openButton)) {
      event.preventDefault();
      const remote = state.remotes.find(
        (item) => item.id === Number(openButton.dataset.openRemote),
      );
      openRemotePopup(remote, openButton.closest(".remote-slide"));
      return;
    }
    const acNode = event.target.closest(".ac-control");
    if (acNode && container.contains(acNode)) {
      event.preventDefault();
      const controls = acNode.closest(".ac-controls");
      const remote = state.remotes.find((item) => item.id === Number(controls?.dataset.deviceId));
      updateACState(remote, acNode);
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

export { loadRemotes, bindRemotesUi, renderRemotes, startRemotesRefresh };
