"use strict";

const shell = document.querySelector(".config-shell");
const remoteSelect = document.querySelector("#remoteSelect");
const columnCount = document.querySelector("#columnCount");
const grid = document.querySelector("#buttonGrid");
const emptyState = document.querySelector("#emptyState");
const addButton = document.querySelector("#addButton");
const remoteTypeBadge = document.querySelector("#remoteTypeBadge");
const rawWorkspace = document.querySelector("#rawWorkspace");
const acWorkspace = document.querySelector("#acWorkspace");
const saveButton = document.querySelector("#saveLayout");
const saveStatus = document.querySelector("#saveStatus");
const remoteActive = document.querySelector("#remoteActive");
const remoteGuestVisible = document.querySelector("#remoteGuestVisible");
const remoteVoiceEnabled = document.querySelector("#remoteVoiceEnabled");
const remoteDeviceName = document.querySelector("#remoteDeviceName");
const remoteDeviceIp = document.querySelector("#remoteDeviceIp");
const syncDeviceIp = document.querySelector("#syncDeviceIp");
const syncIpStatus = document.querySelector("#syncIpStatus");
const layoutTitle = document.querySelector("#layoutTitle");
const editorEmpty = document.querySelector("#editorEmpty");
const editorFields = document.querySelector("#editorFields");
const editorTitle = document.querySelector("#editorTitle");
const configuredBadge = document.querySelector("#configuredBadge");
const captureButton = document.querySelector("#captureSignal");
const captureStatus = document.querySelector("#captureStatus");
const captureDevice = document.querySelector("#captureDevice");
const manualKeyField = document.querySelector("#manualKeyField");
const acProtocol = document.querySelector("#acProtocol");
const acBrand = document.querySelector("#acBrand");
const acModel = document.querySelector("#acModel");
const acStateVersion = document.querySelector("#acStateVersion");
const acConnectionBadge = document.querySelector("#acConnectionBadge");
const acVisibilityContainer = document.querySelector("#acVisibility");
const acPower = document.querySelector("#acPower");
const acTemperature = document.querySelector("#acTemperature");
const acTempMinus = document.querySelector("#acTempMinus");
const acTempPlus = document.querySelector("#acTempPlus");
const acModes = document.querySelector("#acModes");
const acFans = document.querySelector("#acFans");
const acFeatures = document.querySelector("#acFeatures");
const acTestButton = document.querySelector("#acTest");
const acTestStatus = document.querySelector("#acTestStatus");
const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]").value;
const remotes = JSON.parse(document.querySelector("#remote-data").textContent);
const keyChoices = JSON.parse(document.querySelector("#key-choice-data").textContent);
const iconChoices = JSON.parse(document.querySelector("#icon-choice-data").textContent);

const fields = {
  label: document.querySelector("#buttonLabel"),
  key: document.querySelector("#buttonKey"),
  manual_key: document.querySelector("#buttonManualKey"),
  icon: document.querySelector("#buttonIcon"),
  ir_id: document.querySelector("#buttonIrId"),
  frequency: document.querySelector("#buttonFrequency"),
  command_url: document.querySelector("#buttonUrl"),
  raw: document.querySelector("#buttonRaw"),
  is_active: document.querySelector("#buttonActive"),
  requires_confirmation: document.querySelector("#buttonConfirm"),
};

const iconGlyphs = {
  power: "⏻", power_speed: "⏻≋", plus: "＋", minus: "−",
  mode: "⟳", fan: "≋", light: "✦",
  up: "⌃", down: "⌄", left: "‹", right: "›", ok: "OK",
  back: "↩", home: "⌂", menu: "MENU", settings: "⚙",
  info: "ⓘ", guide: "GUIDE", input: "INPUT",
  play: "▶", pause: "Ⅱ", stop: "■", record: "●",
  rewind: "◀◀", fast_forward: "▶▶", previous: "|◀", next: "▶|",
  volume: "◖", volume_up: "VOL＋", volume_down: "VOL−", mute: "MUTE",
  channel_up: "CH＋", channel_down: "CH−",
  cool: "❄", heat: "☀", dry: "💧", swing_vertical: "↕",
  swing_horizontal: "↔", turbo: "⚡", sleep: "☾", timer: "◷", eco: "♧",
  number_0: "0", number_1: "1", number_2: "2", number_3: "3", number_4: "4",
  number_5: "5", number_6: "6", number_7: "7", number_8: "8", number_9: "9",
};

let buttons = [];
let selectedUid = null;
let draggedUid = null;
let dirty = false;
let activeRemote = null;
let captureGeneration = 0;
let acConfig = null;
let acState = null;
let acCapabilities = {};
let acVisibility = {};

const acFeatureLabels = {
  swing_vertical: "تحريك الريش عموديًا",
  swing_horizontal: "تحريك الريش أفقيًا",
  turbo: "توربو",
  sleep: "وضع النوم",
  eco: "توفير الطاقة",
  quiet: "وضع هادئ",
  light: "إضاءة الشاشة",
  x_fan: "تجفيف X-Fan",
};
const acControlLabels = {
  power: "زر التشغيل",
  temperature: "رفع وخفض الحرارة",
  mode: "تغيير الوضع",
  fan: "سرعة المروحة",
  ...acFeatureLabels,
};

function uid(button) {
  return button.id ? `id-${button.id}` : button.client_id;
}

function endpoint(pattern, remoteId) {
  return pattern.replace("/0/", `/${remoteId}/`);
}

function setStatus(message, kind = "") {
  saveStatus.textContent = message;
  saveStatus.className = `save-status ${kind}`.trim();
}

function setCaptureStatus(message, kind = "") {
  captureStatus.textContent = message;
  captureStatus.className = kind;
}

function setSyncStatus(message, kind = "") {
  syncIpStatus.textContent = message;
  syncIpStatus.className = kind;
}

function markDirty() {
  dirty = true;
  setStatus("توجد تغييرات غير محفوظة");
}

function isACRemote() {
  return activeRemote?.device_type === "ac";
}

function selectedProtocol() {
  return acConfig?.protocols?.find((item) => item.value === acProtocol.value) || null;
}

function setACTestStatus(message, kind = "") {
  acTestStatus.textContent = message;
  acTestStatus.className = kind;
}

function renderAC() {
  if (!isACRemote() || !acConfig) return;
  const protocol = selectedProtocol();
  acCapabilities = protocol?.capabilities || {};
  acBrand.textContent = protocol?.brand_label || "—";
  acModel.textContent = protocol?.model_label || "—";
  acStateVersion.textContent = String(acConfig.state_version || 0);
  acConnectionBadge.textContent = activeRemote.device_ip ? `متصل: ${activeRemote.device_ip}` : "غير متصل";
  acConnectionBadge.classList.toggle("connected", Boolean(activeRemote.device_ip));

  acPower.checked = Boolean(acState?.power);
  const min = Number(acCapabilities.temperature_min || 16);
  const max = Number(acCapabilities.temperature_max || 30);
  acState.temperature = Math.min(max, Math.max(min, Number(acState.temperature || 24)));
  acTemperature.textContent = String(acState.temperature);
  acTempMinus.disabled = acState.temperature <= min;
  acTempPlus.disabled = acState.temperature >= max;
  acModes.querySelectorAll("button").forEach((button) => {
    button.classList.toggle("active", button.dataset.value === acState.mode);
  });
  acFans.querySelectorAll("button").forEach((button) => {
    button.classList.toggle("active", button.dataset.value === acState.fan);
  });

  acFeatures.replaceChildren();
  Object.entries(acFeatureLabels).forEach(([field, label]) => {
    if (!acCapabilities[field]) {
      acState[field] = false;
      return;
    }
    const item = document.createElement("label");
    item.className = "feature-toggle";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(acState[field]);
    input.addEventListener("change", () => {
      acState[field] = input.checked;
      item.classList.toggle("active", input.checked);
      setACTestStatus("الحالة جاهزة للإرسال.");
    });
    const text = document.createElement("span");
    text.textContent = label;
    item.classList.toggle("active", input.checked);
    item.append(input, text);
    acFeatures.appendChild(item);
  });

  acVisibilityContainer.replaceChildren();
  Object.entries(acControlLabels).forEach(([field, label]) => {
    if (!acCapabilities[field]) return;
    const item = document.createElement("label");
    item.className = "visibility-toggle";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = acVisibility[field] !== false;
    input.addEventListener("change", () => {
      acVisibility[field] = input.checked;
      item.classList.toggle("active", input.checked);
      markDirty();
    });
    const text = document.createElement("span");
    text.textContent = label;
    item.classList.toggle("active", input.checked);
    item.append(input, text);
    acVisibilityContainer.appendChild(item);
  });
  acTestButton.disabled = !activeRemote.device_ip || !protocol;
}

function renderRemoteType() {
  const isAC = isACRemote();
  rawWorkspace.hidden = isAC;
  acWorkspace.hidden = !isAC;
  columnCount.closest("label").hidden = isAC;
  addButton.hidden = isAC;
  remoteTypeBadge.textContent = isAC ? "مكيف AC" : "ريموت RAW IR";
  remoteTypeBadge.classList.toggle("ac", isAC);
  saveButton.textContent = isAC ? "حفظ إعدادات المكيف" : "حفظ الترتيب والإعدادات";
}

function fillSelect(select, choices, includeEmpty = false) {
  select.replaceChildren();
  if (includeEmpty) select.add(new Option("بدون أيقونة", ""));
  choices.forEach((choice) => select.add(new Option(choice.label, choice.value)));
}

function normalizePositions() {
  const columns = Number(columnCount.value);
  buttons.forEach((button, index) => {
    button.sort_order = index;
    button.row = Math.floor(index / columns);
    button.column = index % columns;
  });
}

function currentButton() {
  return buttons.find((button) => uid(button) === selectedUid) || null;
}

function commitEditor() {
  const button = currentButton();
  if (!button || editorFields.hidden) return true;
  button.label = fields.label.value.trim();
  button.key = fields.key.value === "__manual__" ? fields.manual_key.value.trim() : fields.key.value;
  button.icon = fields.icon.value;
  button.ir_id = Number(fields.ir_id.value || 1);
  button.frequency = Number(fields.frequency.value || 38);
  button.command_url = fields.command_url.value.trim();
  button.raw_text = fields.raw.value.trim() || "[]";
  button.is_active = fields.is_active.checked;
  button.requires_confirmation = fields.requires_confirmation.checked;
  return true;
}

function renderEditor() {
  const button = currentButton();
  editorEmpty.hidden = Boolean(button);
  editorFields.hidden = !button;
  if (!button) return;
  editorTitle.textContent = button.label || "زر جديد";
  fields.label.value = button.label;
  const hasPresetKey = keyChoices.some((choice) => choice.value === button.key);
  fields.key.value = hasPresetKey ? button.key : "__manual__";
  fields.manual_key.value = hasPresetKey ? "" : button.key;
  manualKeyField.hidden = hasPresetKey;
  fields.icon.value = button.icon;
  fields.ir_id.value = button.ir_id;
  fields.frequency.value = button.frequency;
  fields.command_url.value = button.command_url;
  fields.raw.value = button.raw_text ?? JSON.stringify(button.raw || []);
  fields.is_active.checked = button.is_active;
  fields.requires_confirmation.checked = button.requires_confirmation;
  const ready = Boolean(button.configured || (button.command_url && (button.raw || []).length));
  configuredBadge.textContent = ready ? "مهيأ" : "غير مهيأ";
  configuredBadge.classList.toggle("ready", ready);
  captureButton.disabled = !activeRemote?.can_capture;
  captureDevice.textContent = activeRemote?.can_capture
    ? `${activeRemote.device_name || "ESP32"} — ${activeRemote.device_ip}`
    : "زامن عنوان جهاز ESP32 من لوحة الإدارة أولًا.";
}

function renderGrid() {
  normalizePositions();
  grid.style.setProperty("--columns", columnCount.value);
  grid.replaceChildren();
  buttons.forEach((button) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "layout-button";
    card.classList.toggle("selected", uid(button) === selectedUid);
    card.classList.toggle("inactive", !button.is_active);
    card.classList.toggle("configured", Boolean(button.configured));
    card.draggable = true;
    card.dataset.uid = uid(button);

    const handle = document.createElement("span");
    handle.className = "handle";
    handle.textContent = "⋮⋮";
    const icon = document.createElement("span");
    icon.className = "button-icon";
    icon.textContent = iconGlyphs[button.icon] || "•";
    const label = document.createElement("strong");
    label.textContent = button.label || "زر جديد";
    const position = document.createElement("small");
    position.textContent = `${button.row + 1}:${button.column + 1}`;
    card.append(handle, icon, label, position);
    grid.appendChild(card);
  });
  emptyState.hidden = buttons.length > 0;
}

function selectButton(nextUid) {
  commitEditor();
  selectedUid = nextUid;
  renderGrid();
  renderEditor();
}

async function loadRemote() {
  const remoteId = remoteSelect.value;
  if (!remoteId) {
    buttons = [];
    renderGrid();
    return;
  }
  setStatus("جارٍ تحميل الأزرار…");
  const response = await fetch(endpoint(shell.dataset.loadPattern, remoteId), { credentials: "same-origin" });
  if (!response.ok) throw new Error("تعذر تحميل أزرار جهاز التحكم.");
  const data = await response.json();
  activeRemote = data.remote;
  acConfig = data.ac;
  acState = data.ac ? { ...data.ac.state } : null;
  acVisibility = data.ac ? { ...data.ac.visibility } : {};
  remoteActive.checked = activeRemote.is_active;
  remoteGuestVisible.checked = activeRemote.guest_visible;
  remoteVoiceEnabled.checked = activeRemote.voice_enabled;
  remoteDeviceName.value = activeRemote.device_name || "";
  remoteDeviceIp.textContent = activeRemote.device_ip || "—";
  setSyncStatus("");
  setACTestStatus("");
  buttons = data.buttons.map((button) => ({
    ...button,
    client_id: `id-${button.id}`,
    raw_text: JSON.stringify(button.raw || []),
  }));
  const maxColumn = Math.max(1, ...buttons.map((button) => button.column + 1));
  columnCount.value = String(Math.min(maxColumn, 4));
  selectedUid = buttons.length ? uid(buttons[0]) : null;
  dirty = false;
  layoutTitle.textContent = data.remote.name;
  renderRemoteType();
  if (acConfig) {
    acProtocol.replaceChildren(new Option("اختر البروتوكول…", ""));
    acConfig.protocols.forEach((item) => acProtocol.add(new Option(item.label, item.value)));
    acProtocol.value = acConfig.protocol || "";
    renderAC();
  }
  setStatus("");
  renderGrid();
  renderEditor();
}

async function captureRequest(pattern, options = {}) {
  const response = await fetch(endpoint(pattern, remoteSelect.value), {
    credentials: "same-origin",
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "تعذر الاتصال بجهاز ESP32.");
  return data;
}

async function syncIp() {
  const deviceName = remoteDeviceName.value.trim();
  if (!deviceName) {
    setSyncStatus("أدخل Device name أولًا.", "error");
    return;
  }
  syncDeviceIp.disabled = true;
  setSyncStatus("جارٍ البحث عن الجهاز…");
  try {
    const data = await captureRequest(shell.dataset.syncIpPattern, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify({ device_name: deviceName }),
    });
    activeRemote.device_name = data.device_name;
    activeRemote.device_ip = data.device_ip;
    activeRemote.can_capture = true;
    remoteDeviceIp.textContent = data.device_ip;
    buttons.forEach((button) => {
      button.command_url = data.command_url;
      if (button.raw?.length) button.configured = true;
    });
    setSyncStatus(
      isACRemote()
        ? `تم ربط وحدة المكيف على ${data.device_ip}`
        : `تمت المزامنة: ${data.device_ip} — تم تحديث ${data.updated_buttons} زر`,
      "success",
    );
    renderAC();
    renderGrid();
    renderEditor();
  } catch (error) {
    setSyncStatus(error.message, "error");
  } finally {
    syncDeviceIp.disabled = false;
  }
}

async function pollCapture(generation, targetUid, deadline) {
  if (generation !== captureGeneration || Date.now() > deadline) {
    if (generation === captureGeneration) {
      captureButton.disabled = !activeRemote?.can_capture;
      setCaptureStatus("انتهت مهلة القراءة. حاول مرة أخرى.", "error");
    }
    return;
  }
  try {
    const data = await captureRequest(shell.dataset.captureStatusPattern);
    if (generation !== captureGeneration) return;
    if (data.ready) {
      const button = buttons.find((item) => uid(item) === targetUid);
      if (!button) throw new Error("لم يعد الزر المحدد متاحًا.");
      button.frequency = data.frequency;
      button.raw = data.raw;
      button.raw_text = JSON.stringify(data.raw);
      button.configured = true;
      selectedUid = targetUid;
      captureButton.disabled = !activeRemote?.can_capture;
      setCaptureStatus(
        `تمت قراءة ${data.raw.length} نبضة${data.protocol ? ` — ${data.protocol}` : ""}. اضغط حفظ.`,
        "success",
      );
      markDirty();
      renderGrid();
      renderEditor();
      return;
    }
    if (!data.capturing) {
      captureButton.disabled = !activeRemote?.can_capture;
      setCaptureStatus("لم يتم استقبال إشارة. حاول مرة أخرى.", "error");
      return;
    }
    setTimeout(() => pollCapture(generation, targetUid, deadline), 700);
  } catch (error) {
    captureButton.disabled = !activeRemote?.can_capture;
    setCaptureStatus(error.message, "error");
  }
}

async function startCapture() {
  commitEditor();
  const button = currentButton();
  if (!button || !activeRemote?.can_capture) return;
  const generation = ++captureGeneration;
  const targetUid = uid(button);
  captureButton.disabled = true;
  setCaptureStatus("جارٍ تفعيل قارئ IR…");
  try {
    const data = await captureRequest(shell.dataset.captureStartPattern, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify({ frequency: Number(fields.frequency.value || 38) }),
    });
    setCaptureStatus("القارئ جاهز. اضغط زرًا واحدًا في الريموت الآن.");
    const timeout = Math.max(3000, Number(data.timeout_ms || 15000) + 2000);
    setTimeout(() => pollCapture(generation, targetUid, Date.now() + timeout), 500);
  } catch (error) {
    captureButton.disabled = !activeRemote?.can_capture;
    setCaptureStatus(error.message, "error");
  }
}

function unusedKey() {
  const used = new Set(buttons.map((button) => button.key));
  return keyChoices.find((choice) => !used.has(choice.value));
}

function addNewButton() {
  commitEditor();
  const choice = unusedKey();
  if (!choice) {
    setStatus("استُخدمت جميع وظائف الأزرار المتاحة.", "error");
    return;
  }
  const button = {
    id: null,
    client_id: `new-${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`,
    key: choice.value,
    label: choice.label,
    icon: "",
    row: 0,
    column: 0,
    sort_order: buttons.length,
    command_url: "",
    ir_id: 1,
    frequency: 38,
    raw: [],
    raw_text: "[]",
    is_active: true,
    requires_confirmation: false,
    configured: false,
  };
  buttons.push(button);
  selectedUid = uid(button);
  markDirty();
  renderGrid();
  renderEditor();
}

function moveSelected(offset) {
  commitEditor();
  const index = buttons.findIndex((button) => uid(button) === selectedUid);
  const target = index + offset;
  if (index < 0 || target < 0 || target >= buttons.length) return;
  [buttons[index], buttons[target]] = [buttons[target], buttons[index]];
  markDirty();
  renderGrid();
}

function payloadButtons() {
  commitEditor();
  normalizePositions();
  const seenKeys = new Set();
  return buttons.map((button) => {
    let raw;
    try {
      raw = JSON.parse(button.raw_text || "[]");
    } catch {
      throw new Error(`نبضات IR للزر «${button.label}» ليست JSON صحيحة.`);
    }
    if (!button.label) throw new Error("يجب إدخال اسم لكل زر.");
    if (seenKeys.has(button.key)) throw new Error("لا يمكن تكرار وظيفة الزر في الجهاز نفسه.");
    seenKeys.add(button.key);
    return {
      id: button.id,
      key: button.key,
      label: button.label,
      icon: button.icon,
      row: button.row,
      column: button.column,
      sort_order: button.sort_order,
      command_url: button.command_url,
      ir_id: button.ir_id,
      frequency: button.frequency,
      raw,
      is_active: button.is_active,
      requires_confirmation: button.requires_confirmation,
    };
  });
}

async function saveLayout(reload = true) {
  try {
    const payload = {
      remote: {
        device_name: remoteDeviceName.value.trim(),
        is_active: remoteActive.checked,
        guest_visible: remoteGuestVisible.checked,
        voice_enabled: remoteVoiceEnabled.checked,
        protocol: isACRemote() ? acProtocol.value : "",
        ac_control_visibility: isACRemote() ? acVisibility : {},
      },
      buttons: payloadButtons(),
    };
    saveButton.disabled = true;
    setStatus("جارٍ الحفظ…");
    const response = await fetch(endpoint(shell.dataset.savePattern, remoteSelect.value), {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const details = data.errors ? ` ${JSON.stringify(data.errors)}` : "";
      throw new Error(`${data.detail || "تعذر حفظ الأزرار."}${details}`);
    }
    dirty = false;
    setStatus("تم الحفظ بنجاح", "success");
    if (reload) {
      await loadRemote();
      setStatus("تم الحفظ بنجاح", "success");
    }
    return true;
  } catch (error) {
    setStatus(error.message, "error");
    return false;
  } finally {
    saveButton.disabled = false;
  }
}

async function testACState() {
  if (!isACRemote()) return;
  if (!acProtocol.value) {
    setACTestStatus("اختر بروتوكول المكيف أولًا.", "error");
    return;
  }
  if (!activeRemote.device_ip) {
    setACTestStatus("نفّذ Sync IP قبل إرسال الأمر.", "error");
    return;
  }
  acTestButton.disabled = true;
  setACTestStatus("جارٍ حفظ الإعداد ثم إرسال الحالة للمكيف…");
  const saved = await saveLayout(false);
  if (!saved) {
    acTestButton.disabled = false;
    setACTestStatus("تعذر حفظ إعداد البروتوكول.", "error");
    return;
  }
  const state = {
    power: Boolean(acState.power),
    mode: acState.mode,
    temperature: Number(acState.temperature),
    fan: acState.fan,
  };
  Object.keys(acFeatureLabels).forEach((field) => {
    if (acCapabilities[field]) state[field] = Boolean(acState[field]);
  });
  try {
    const data = await captureRequest(shell.dataset.acTestPattern, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify({ state }),
    });
    acState = { ...data.state };
    acConfig.state_version = data.state_version;
    setACTestStatus(`تم الإرسال بنجاح — الإصدار ${data.state_version}`, "success");
    renderAC();
  } catch (error) {
    setACTestStatus(error.message, "error");
  } finally {
    acTestButton.disabled = false;
  }
}

grid.addEventListener("click", (event) => {
  const card = event.target.closest(".layout-button");
  if (card) selectButton(card.dataset.uid);
});

grid.addEventListener("dragstart", (event) => {
  const card = event.target.closest(".layout-button");
  if (!card) return;
  commitEditor();
  draggedUid = card.dataset.uid;
  card.classList.add("dragging");
  event.dataTransfer.effectAllowed = "move";
});

grid.addEventListener("dragover", (event) => {
  event.preventDefault();
  const dragged = grid.querySelector(`[data-uid="${draggedUid}"]`);
  const target = event.target.closest(".layout-button");
  if (!dragged || !target || dragged === target) return;
  const rect = target.getBoundingClientRect();
  const before = event.clientY < rect.top + rect.height / 2 || event.clientX > rect.left + rect.width / 2;
  grid.insertBefore(dragged, before ? target : target.nextSibling);
});

grid.addEventListener("drop", (event) => {
  event.preventDefault();
  const order = [...grid.querySelectorAll(".layout-button")].map((node) => node.dataset.uid);
  const byUid = new Map(buttons.map((button) => [uid(button), button]));
  buttons = order.map((id) => byUid.get(id));
  markDirty();
  renderGrid();
});

grid.addEventListener("dragend", () => {
  draggedUid = null;
  grid.querySelectorAll(".dragging").forEach((node) => node.classList.remove("dragging"));
});

Object.entries(fields).forEach(([name, element]) => {
  element.addEventListener("input", () => {
    const button = currentButton();
    if (!button) return;
    if (name === "is_active" || name === "requires_confirmation") button[name] = element.checked;
    else if (name === "ir_id" || name === "frequency") button[name] = Number(element.value || 0);
    else if (name === "raw") button.raw_text = element.value;
    else if (name === "manual_key") {
      if (fields.key.value === "__manual__") button.key = element.value.trim();
    }
    else if (name === "key") {
      manualKeyField.hidden = element.value !== "__manual__";
      button.key = element.value === "__manual__" ? fields.manual_key.value.trim() : element.value;
    }
    else button[name] = element.value;
    if (name === "label") editorTitle.textContent = element.value || "زر جديد";
    markDirty();
    if (["label", "icon", "is_active"].includes(name)) renderGrid();
  });
});

document.querySelectorAll("[data-move]").forEach((button) => {
  button.addEventListener("click", () => moveSelected(Number(button.dataset.move)));
});
remoteSelect.addEventListener("change", () => {
  captureGeneration += 1;
  setCaptureStatus("");
  loadRemote().catch((error) => setStatus(error.message, "error"));
});
columnCount.addEventListener("change", () => { markDirty(); renderGrid(); });
addButton.addEventListener("click", addNewButton);
saveButton.addEventListener("click", () => saveLayout());
captureButton.addEventListener("click", startCapture);

acProtocol.addEventListener("change", () => {
  markDirty();
  renderAC();
});
acPower.addEventListener("change", () => {
  acState.power = acPower.checked;
  setACTestStatus("الحالة جاهزة للإرسال.");
});
[acModes, acFans].forEach((group) => {
  group.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-value]");
    if (!button) return;
    acState[group === acModes ? "mode" : "fan"] = button.dataset.value;
    setACTestStatus("الحالة جاهزة للإرسال.");
    renderAC();
  });
});
function changeTemperature(delta) {
  acState.temperature += delta;
  setACTestStatus("الحالة جاهزة للإرسال.");
  renderAC();
}
acTempMinus.addEventListener("click", () => changeTemperature(-1));
acTempPlus.addEventListener("click", () => changeTemperature(1));
acTestButton.addEventListener("click", testACState);
[remoteActive, remoteGuestVisible, remoteVoiceEnabled, remoteDeviceName].forEach((field) => {
  field.addEventListener("change", markDirty);
});
syncDeviceIp.addEventListener("click", syncIp);
window.addEventListener("beforeunload", (event) => {
  if (!dirty) return;
  event.preventDefault();
});

fillSelect(fields.key, keyChoices);
fields.key.add(new Option("تحديد يدوي…", "__manual__"));
fillSelect(fields.icon, iconChoices, true);
loadRemote().catch((error) => setStatus(error.message, "error"));
