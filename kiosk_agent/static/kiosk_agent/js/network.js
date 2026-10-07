"use strict";

import { headers } from "./api.js";

const WIFI_URL = "/api/v1/kiosk/wifi/";
const WIFI_CONNECT_URL = "/api/v1/kiosk/wifi/connect/";

const $ = (id) => document.getElementById(id);

function clientLabel() {
  const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  if (!conn) return navigator.onLine ? "متصل" : "غير متصل";
  const typeNames = {
    wifi: "واي فاي", cellular: "بيانات الجوال", ethernet: "سلكي",
    bluetooth: "بلوتوث", wimax: "واي ماكس", none: "لا يوجد", unknown: "",
  };
  const parts = [];
  if (conn.type && typeNames[conn.type]) parts.push(typeNames[conn.type]);
  else if (conn.type) parts.push(conn.type);
  if (conn.effectiveType) parts.push(String(conn.effectiveType).toUpperCase());
  if (conn.downlink) parts.push(`${conn.downlink} Mb/s`);
  return parts.join(" · ") || (navigator.onLine ? "متصل" : "غير متصل");
}

function signalBars(signal) {
  if (signal >= 75) return "▂▄▆█";
  if (signal >= 50) return "▂▄▆";
  if (signal >= 25) return "▂▄";
  return "▂";
}

function showMessage(messageEl, text, kind) {
  messageEl.hidden = false;
  messageEl.textContent = text;
  messageEl.className = `wifi-message is-${kind}`;
}

function hideMessage(messageEl) {
  messageEl.hidden = true;
  messageEl.textContent = "";
}

export function initNetworkPopover() {
  const pill = $("connectionPill");
  const popover = $("networkPopover");
  if (!pill || !popover) return;

  const ui = {
    state: $("networkState"), ssid: $("networkSsid"), ip: $("networkIp"),
    host: $("networkHost"), client: $("networkClient"), latency: $("networkLatency"),
    updatedAt: $("networkUpdatedAt"), refresh: $("networkRefresh"), copy: $("networkCopy"),
    rescan: $("wifiRescan"), list: $("wifiList"), form: $("wifiJoinForm"),
    selectedSsid: $("wifiSelectedSsid"), password: $("wifiPassword"),
    message: $("wifiMessage"), cancel: $("wifiCancel"), connect: $("wifiConnect"),
  };

  let open = false;
  let loading = false;
  let selected = null;
  let lastData = null;
  let lastLatency = null;

  function positionPopover() {
    // Small screens: bottom-sheet mode handled purely by CSS class.
    if (window.innerWidth <= 800) {
      popover.classList.add("is-sheet");
      popover.style.top = "";
      popover.style.left = "";
      popover.style.right = "";
      popover.style.bottom = "";
      return;
    }
    popover.classList.remove("is-sheet");
    // Anchor under the pill, inline-end aligned; clamp inside the viewport.
    const rect = pill.getBoundingClientRect();
    const width = Math.min(340, window.innerWidth - 24);
    let left = rect.right - width;
    left = Math.max(8, Math.min(left, window.innerWidth - width - 8));
    popover.style.left = `${Math.round(left)}px`;
    popover.style.right = "auto";
    popover.style.bottom = "auto";
    const below = rect.bottom + 10;
    // Flip above the pill if there is no room below.
    const height = Math.min(popover.offsetHeight || 400, window.innerHeight * 0.7);
    popover.style.top = (below + height > window.innerHeight && rect.top - height - 10 > 8)
      ? `${Math.round(rect.top - height - 10)}px`
      : `${Math.round(below)}px`;
  }

  function setOpen(value) {
    open = value;
    popover.hidden = !value;
    pill.setAttribute("aria-expanded", String(value));
    if (value) {
      positionPopover();
      refresh(false);
      ui.rescan?.focus({ preventScroll: true });
    } else {
      pill.focus({ preventScroll: true });
    }
  }

  async function refresh(rescan) {
    if (loading) return;
    loading = true;
    if (ui.rescan) {
      ui.rescan.disabled = true;
      ui.rescan.textContent = "جارٍ البحث…";
    }
    const started = performance.now();
    try {
      const url = rescan ? `${WIFI_URL}?rescan=1` : WIFI_URL;
      const response = await fetch(url, { headers: headers() });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      lastLatency = Math.round(performance.now() - started);
      lastData = data;
      render(data, lastLatency);
    } catch (error) {
      console.debug("[Network] wifi status failed", error);
      ui.state.textContent = navigator.onLine ? "متصل (تعذر قراءة الواي فاي)" : "غير متصل";
      renderList([]);
    } finally {
      loading = false;
      if (ui.rescan) {
        ui.rescan.disabled = false;
        ui.rescan.textContent = "بحث مجدد";
      }
    }
  }

  function render(data, latencyMs) {
    const wifi = data.wifi || {};
    const network = data.network || {};
    ui.state.textContent = wifi.connected && wifi.ssid
      ? `متصل — ${wifi.ssid}`
      : (navigator.onLine ? "متصل" : "غير متصل");
    ui.ssid.textContent = wifi.ssid || network.ssid || "—";
    ui.ip.textContent = network.local_ip || "—";
    ui.host.textContent = network.hostname || "—";
    ui.client.textContent = clientLabel();
    ui.latency.textContent = latencyMs == null ? "—" : `${latencyMs} ms`;
    ui.updatedAt.textContent = new Date().toLocaleTimeString("ar", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    renderList(wifi.networks || [], wifi.available);
  }

  function renderList(networks, available) {
    ui.list.textContent = "";
    if (available === false) {
      const empty = document.createElement("li");
      empty.className = "wifi-empty";
      empty.textContent = "التحكم بالواي فاي غير متاح على هذا الجهاز — أعد بناء الحاوية مع دعم NetworkManager.";
      ui.list.append(empty);
      return;
    }
    if (!networks.length) {
      const empty = document.createElement("li");
      empty.className = "wifi-empty";
      empty.textContent = "لا توجد شبكات ظاهرة — اضغط «بحث مجدد».";
      ui.list.append(empty);
      return;
    }
    for (const net of networks.slice(0, 20)) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "wifi-item" + (net.active ? " is-active" : "");
      button.setAttribute("aria-label", `الاتصال بشبكة ${net.ssid}${net.active ? " (متصلة حالياً)" : ""}`);
      if (net.active) button.disabled = true;

      const bars = document.createElement("span");
      bars.className = "wifi-signal";
      bars.textContent = signalBars(net.signal);
      bars.title = `${net.signal}%`;
      bars.setAttribute("aria-hidden", "true");

      const name = document.createElement("span");
      name.className = "wifi-name";
      name.dir = "ltr";
      name.textContent = net.ssid;

      const lock = document.createElement("span");
      lock.className = "wifi-lock";
      lock.textContent = net.secured ? "🔒" : "🔓";
      lock.title = net.secured ? "مؤمنة" : "مفتوحة";
      lock.setAttribute("aria-hidden", "true");

      button.append(bars, name, lock);
      if (net.saved && !net.active) {
        const saved = document.createElement("span");
        saved.className = "wifi-saved";
        saved.textContent = "محفوظة";
        button.append(saved);
      }
      if (net.active) {
        const check = document.createElement("span");
        check.className = "wifi-check";
        check.textContent = "✓";
        check.setAttribute("aria-hidden", "true");
        button.append(check);
      }
      if (!net.active) {
        button.addEventListener("click", () => selectNetwork(net));
      }
      item.append(button);
      ui.list.append(item);
    }
  }

  function selectNetwork(net) {
    selected = net;
    ui.form.hidden = false;
    ui.selectedSsid.textContent = net.ssid;
    hideMessage(ui.message);
    const field = ui.password.closest(".wifi-field");
    // Saved networks reuse their stored password — typing a new one replaces it.
    const needPassword = net.secured && !net.saved;
    if (net.secured) {
      field.style.display = "";
      ui.password.required = needPassword;
      ui.password.value = "";
      ui.password.placeholder = net.saved ? "محفوظة — اتركها فارغة للاتصال المباشر" : "8 أحرف على الأقل";
      if (needPassword) ui.password.focus({ preventScroll: true });
    } else {
      field.style.display = "none";
      ui.password.required = false;
      ui.password.value = "";
    }
    ui.form.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function cancelJoin() {
    selected = null;
    ui.form.hidden = true;
    ui.password.value = "";
    hideMessage(ui.message);
  }

  async function submitJoin(event) {
    event.preventDefault();
    if (!selected || loading) return;
    const password = ui.password.value || "";
    if (password ? password.length < 8 : (selected.secured && !selected.saved)) {
      showMessage(ui.message, "كلمة المرور 8 أحرف على الأقل.", "error");
      ui.password.focus();
      return;
    }
    if (!window.confirm(`الاتصال بشبكة «${selected.ssid}»؟ سينقطع الجهاز عن الشبكة مؤقتاً.`)) return;
    loading = true;
    ui.connect.disabled = true;
    showMessage(ui.message, "جارٍ الاتصال… قد ينقطع الاتصال مؤقتاً لمدة تصل إلى 30 ثانية.", "info");
    try {
      const response = await fetch(WIFI_CONNECT_URL, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ ssid: selected.ssid, password, security: selected.security || "" }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.success) {
        throw new Error(data.detail || `HTTP ${response.status}`);
      }
      showMessage(ui.message, `تم الاتصال بـ «${data.ssid || selected.ssid}» بنجاح. يتم التحقق…`, "success");
      ui.password.value = "";
      // Poll to confirm the radio actually settled on the new SSID.
      for (let attempt = 0; attempt < 3; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 3000));
        await refresh(false);
        if (lastData?.wifi?.ssid === selected.ssid) break;
      }
    } catch (error) {
      console.debug("[Network] wifi connect failed", error);
      showMessage(ui.message, String(error.message || "تعذر الاتصال. تحقق من كلمة المرور وحاول مجدداً."), "error");
    } finally {
      loading = false;
      ui.connect.disabled = false;
    }
  }

  async function copyDiagnostics() {
    const wifi = lastData?.wifi || {};
    const network = lastData?.network || {};
    const text = [
      `SSID: ${wifi.ssid || network.ssid || "-"}`,
      `IP: ${network.local_ip || "-"}`,
      `Host: ${network.hostname || "-"}`,
      `Client: ${clientLabel()}`,
      `Latency: ${lastLatency == null ? "-" : `${lastLatency} ms`}`,
      `Connectivity: ${wifi.connectivity || "-"}`,
    ].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      ui.copy.textContent = "تم النسخ ✓";
    } catch (error) {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.append(area);
      area.select();
      try { document.execCommand("copy"); ui.copy.textContent = "تم النسخ ✓"; }
      catch { ui.copy.textContent = "تعذر النسخ"; }
      area.remove();
    }
    window.setTimeout(() => { ui.copy.textContent = "نسخ التشخيص"; }, 2000);
  }

  pill.addEventListener("click", (event) => {
    event.stopPropagation();
    setOpen(!open);
  });
  document.addEventListener("click", (event) => {
    if (open && !popover.contains(event.target) && event.target !== pill && !pill.contains(event.target)) {
      setOpen(false);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && open) setOpen(false);
  });
  ui.refresh.addEventListener("click", () => refresh(false));
  ui.rescan.addEventListener("click", () => refresh(true));
  ui.copy.addEventListener("click", copyDiagnostics);
  ui.cancel.addEventListener("click", cancelJoin);
  ui.form.addEventListener("submit", submitJoin);
  window.addEventListener("resize", () => { if (open) positionPopover(); });

  // Keep the client-side line fresh while open (cheap, no server call).
  window.setInterval(() => {
    if (!open || !lastData) return;
    ui.client.textContent = clientLabel();
  }, 5000);
}
