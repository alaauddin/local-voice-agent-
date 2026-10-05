// Presentation only. Commands are handled by remotes.js through data attributes.
const MODE_LABELS = { auto: "تلقائي", cool: "تبريد", heat: "تدفئة", dry: "تجفيف", fan: "مروحة فقط" };
const FAN_LABELS = { auto: "تلقائية", low: "منخفضة", medium: "متوسطة", high: "عالية" };
const FEATURES = {
  swing_vertical: ["توجيه الهواء", "swing"], swing_horizontal: ["توجيه أفقي", "swing"],
  sleep: ["النمط الليلي", "sleep"], turbo: ["توربو", "turbo"], eco: ["اقتصادي", "eco"],
  quiet: ["هادئ", "volume"], light: ["إضاءة", "light"], x_fan: ["تجفيف داخلي", "fan"],
};
const PATHS = {
  ac: '<rect x="2" y="5" width="20" height="12" rx="2"/><path d="M5 13h14M7 17v3m10-3v3M5 9h2"/>',
  power: '<path d="M12 2v10M6 5a9 9 0 1 0 12 0"/>',
  fan: '<circle cx="12" cy="12" r="2"/><path d="M10 10C3 3 12 0 13 5l-1 5m2 0c7-7 10 2 5 3l-5-1m0 2c7 7-2 10-3 5l1-5m-2 0C3 21 0 12 5 11l5 1"/>',
  cool: '<path d="M12 2v20M3.3 7l17.4 10M3.3 17 20.7 7M9 4l3 3 3-3M9 20l3-3 3 3M4 10l4-1-1-4m10 14-1-4 4-1M7 19l1-4-4-1m16-4-4-1 1-4"/>',
  mode: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  timer: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l3 2"/>',
  sleep: '<path d="M19.8 15A8.5 8.5 0 0 1 9 4.2 8.5 8.5 0 1 0 19.8 15Z"/>',
  swing: '<path d="M12 2v6m-3-3 3-3 3 3m-3 17v-6m-3 3 3 3 3-3M2 12h6m-3-3-3 3 3 3m17-3h-6m3-3 3 3-3 3"/>',
  light: '<path d="M9 18h6m-5 3h4M8 15c0-3-3-3-3-7a7 7 0 0 1 14 0c0 4-3 4-3 7Z"/>',
  tv: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M12 17v4m-5 0h10"/>',
  curtain: '<path d="M2 3h20M4 3v18l5-3-3-7 3-8m11 0v18l-5-3 3-7-3-8M9 3h6"/>',
  volume: '<path d="m3 9 4 0 5-5v16l-5-5H3Zm13-1a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
  up: '<path d="m7 14 5-5 5 5"/>', down: '<path d="m7 10 5 5 5-5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>', minus: '<path d="M5 12h14"/>',
  pause: '<path d="M8 5v14M16 5v14" stroke-width="4"/>',
  turbo: '<path d="m13 2-9 12h7l-1 8 10-13h-8Z"/>',
  eco: '<path d="M4 20C0 8 10 3 21 3c0 11-5 18-14 14M4 20 16 8"/>',
  device: '<rect x="6" y="2" width="12" height="20" rx="3"/><circle cx="12" cy="7" r="1"/><path d="M9 12h6m-3-3v6m-3 3h6"/>',
};
const ALIASES = { power_speed: "fan", heat: "light", dry: "eco", auto: "mode", swing_vertical: "swing", swing_horizontal: "swing", volume_up: "plus", volume_down: "minus", mute: "volume", stop: "pause" };

export function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.6");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = PATHS[ALIASES[name] || name] || PATHS.device;
  return svg;
}
function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function control(label, field, action, glyph, active = false) {
  const node = element("button", "ac-control dashboard-control", label);
  node.type = "button";
  node.dataset.field = field;
  node.dataset.action = action;
  node.setAttribute("aria-label", label);
  node.replaceChildren(icon(glyph), element("span", "dashboard-control-label", label));
  if (action === "toggle") node.setAttribute("aria-pressed", String(active));
  node.classList.toggle("is-active", active);
  return node;
}
function rawButton(button) {
  const node = element("button", "remote-button dashboard-control");
  node.type = "button";
  node.dataset.buttonId = String(button.id);
  node.dataset.key = button.key;
  node.dataset.icon = button.icon || "";
  if (/^(off|power_off)$/.test(button.key) || /إطفاء|إيقاف|ايقاف/.test(button.label)) {
    node.dataset.powerAction = "off";
  }
  node.disabled = !button.configured;
  node.title = button.configured ? button.label : `${button.label} — غير مهيأ بعد`;
  node.setAttribute("aria-label", node.title);
  node.append(icon(button.icon), element("span", "dashboard-control-label", button.label));
  return node;
}
function deviceKind(remote) {
  if (remote.device_type === "ac") return "ac";
  const name = `${remote.name} ${remote.slug}`;
  if (/ستار|ستائر|curtain/i.test(name)) return "curtain";
  if (/تلف|تلفاز|tv|television/i.test(name)) return "tv";
  if (/إضاء|اضاء|مصباح|light|lamp/i.test(name)) return "light";
  if (/مروح|fan/i.test(name)) return "fan";
  return "device";
}
function buildAC(remote) {
  const current = remote.ac_state;
  const caps = remote.ac_capabilities || {};
  const body = element("div", "dashboard-ac ac-controls");
  body.dataset.deviceId = String(remote.id);
  if (!current) {
    body.append(element("p", "device-empty", "حالة المكيف غير متاحة"));
    return body;
  }
  const display = element("div", "dashboard-ac-display");
  const temperature = element("div", "dashboard-temperature");
  const reading = element("div", "dashboard-temperature-reading");
  reading.append(element("strong", "", String(current.temperature)), element("span", "", "°C"));
  temperature.append(reading, element("small", "", "درجة الحرارة الحالية"));
  const arrows = element("div", "dashboard-temperature-arrows");
  if (caps.temperature) {
    const up = control("رفع درجة الحرارة", "temperature", "increase", "up");
    const down = control("خفض درجة الحرارة", "temperature", "decrease", "down");
    up.disabled = current.temperature >= (caps.temperature_max ?? 32);
    down.disabled = current.temperature <= (caps.temperature_min ?? 16);
    arrows.append(up, down);
  }
  const details = element("div", "dashboard-ac-details");
  for (const [label, value, glyph] of [
    ["الوضع الحالي", MODE_LABELS[current.mode] || current.mode, current.mode],
    ["سرعة المروحة", FAN_LABELS[current.fan] || current.fan, "fan"],
  ]) {
    const row = element("div", `dashboard-detail detail-${glyph}`);
    const copy = element("div", "");
    copy.append(element("small", "", label), element("strong", "", value));
    row.append(icon(glyph), copy);
    details.append(row);
  }
  display.append(details, temperature, arrows);
  const actions = element("div", "dashboard-ac-actions");
  if (caps.power) {
    const power = control(current.power ? "إيقاف التشغيل" : "تشغيل", "power", "toggle", "power", current.power);
    power.classList.add(current.power ? "will-stop" : "will-start");
    actions.append(power);
  }
  if (caps.mode) actions.append(control("الوضع", "mode", "cycle", "mode"));
  if (caps.fan) actions.append(control("السرعة", "fan", "cycle", "fan"));
  for (const field of ["swing_vertical", "swing_horizontal", "sleep"]) {
    if (caps[field]) actions.append(control(FEATURES[field][0], field, "toggle", FEATURES[field][1], current[field]));
  }
  // Timers are rendered only when a real configured device command exists.
  const timer = (remote.buttons || []).find(button => button.icon === "timer" && button.configured);
  if (timer) actions.insertBefore(rawButton(timer), actions.lastChild);
  body.append(display, actions);
  const extras = element("details", "dashboard-extra");
  const extraActions = element("div", "dashboard-ac-actions");
  for (const [field, [label, glyph]] of Object.entries(FEATURES)) {
    if (caps[field] && !["swing_vertical", "swing_horizontal", "sleep"].includes(field)) {
      extraActions.append(control(label, field, "toggle", glyph, current[field]));
    }
  }
  if (extraActions.childElementCount) {
    extras.append(element("summary", "", "خيارات إضافية"), extraActions);
    body.append(extras);
  }
  return body;
}
function buildGeneric(remote, expanded) {
  const body = element("div", "dashboard-generic");
  const buttons = [...(remote.buttons || [])].sort((a, b) => a.sort_order - b.sort_order || a.row - b.row || a.column - b.column);
  if (!buttons.length) {
    body.append(element("p", "device-empty", "لم تتم تهيئة أزرار هذا الجهاز بعد"));
    return body;
  }
  const power = buttons.filter(button => /power/.test(button.icon || "") || /^(on|off|power_on|power_off)$/.test(button.key));
  const others = buttons.filter(button => !power.includes(button));
  if (power.length) {
    const strip = element("div", "dashboard-power-strip");
    power.forEach(button => strip.append(rawButton(button)));
    body.append(strip);
  }
  const grid = element("div", "dashboard-generic-actions");
  (expanded ? others : others.slice(0, 6)).forEach(button => grid.append(rawButton(button)));
  body.append(grid);
  if (!expanded && others.length > 6) {
    const more = element("button", "dashboard-more", "كل الأزرار");
    more.type = "button";
    more.dataset.openRemote = String(remote.id);
    body.append(more);
  }
  return body;
}
function lgButton(label, command, className = "") {
  const button = element("button", `lg-tv-control ${className}`.trim(), label);
  button.type = "button";
  button.dataset.lgCommand = command;
  return button;
}
function buildLGTV(remote, expanded) {
  const body = element("div", "dashboard-generic lg-tv-remote");
  body.dataset.deviceId = String(remote.id);
  if (!expanded) {
    const open = element("button", "dashboard-control lg-tv-open", "فتح الريموت");
    open.type = "button";
    open.dataset.openRemote = String(remote.id);
    open.setAttribute("aria-label", `فتح ريموت ${remote.name}`);
    open.prepend(icon("device"));
    body.append(open);
    return body;
  }
  body.classList.add("is-expanded");
  const power = lgButton("⏻", "POWER", "lg-power");
  const main = element("div", "lg-button-row");
  main.append(lgButton("INPUT", "INPUT"), lgButton("HOME", "HOME"), lgButton("SETTINGS", "SETTINGS"));
  const rockers = element("div", "lg-rockers");
  const volume = element("div", "lg-rocker");
  volume.append(lgButton("VOL +", "VOL_UP"), lgButton("VOL −", "VOL_DOWN"));
  const channel = element("div", "lg-rocker");
  channel.append(lgButton("CH +", "CH_UP"), lgButton("CH −", "CH_DOWN"));
  rockers.append(volume, lgButton("MUTE", "MUTE", "lg-mute"), channel);
  const dpad = element("div", "lg-dpad");
  dpad.append(
    lgButton("▲", "UP", "lg-up"),
    lgButton("◀", "LEFT", "lg-left"),
    lgButton("OK", "OK", "lg-ok"),
    lgButton("▶", "RIGHT", "lg-right"),
    lgButton("▼", "DOWN", "lg-down"),
  );
  const utility = element("div", "lg-button-row lg-utility");
  utility.append(lgButton("BACK", "BACK"), lgButton("EXIT", "EXIT"));
  const numbers = element("div", "lg-numbers");
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"].forEach(number => {
    numbers.append(lgButton(number, number, number === "0" ? "lg-zero" : ""));
  });
  body.append(power, main, rockers, dpad, utility, numbers);
  return body;
}

export function buildRemoteCard(remote, expanded = false) {
  const kind = deviceKind(remote);
  const card = element("article", `remote-slide dashboard-device device-${kind}${expanded ? " is-expanded" : ""}`);
  card.dataset.remoteId = String(remote.id);
  card.dataset.deviceKind = kind;
  if (remote.device_type === "lg_tv") card.classList.add("device-tv");
  const heading = element("header", "dashboard-device-heading");
  const deviceIcon = element("span", "dashboard-device-icon");
  deviceIcon.append(icon(kind));
  const copy = element("div", "dashboard-device-copy");
  copy.append(element("strong", "", remote.name), element("small", "", remote.location || "داخل الشاليه"));
  const status = element("span", "dashboard-device-status");
  if (remote.device_type === "lg_tv") {
    status.textContent = "ريموت مخصص";
    status.classList.add("is-on");
  } else if (kind === "ac") {
    status.textContent = !remote.ac_state ? "غير متاح" : remote.ac_state.power ? "يعمل الآن" : "متوقف";
    status.classList.toggle("is-on", Boolean(remote.ac_state?.power));
  } else {
    const configured = (remote.buttons || []).some(button => button.configured);
    status.textContent = configured ? "مهيأ" : "غير مهيأ";
    status.classList.toggle("is-on", configured);
  }
  heading.append(deviceIcon, copy, status);
  if (!expanded) {
    const more = element("button", "remote-open-button", "···");
    more.type = "button";
    more.dataset.openRemote = String(remote.id);
    more.setAttribute("aria-label", `فتح جهاز التحكم ${remote.name}`);
    heading.append(more);
  }
  card.append(heading, remote.device_type === "lg_tv" ? buildLGTV(remote, expanded) : kind === "ac" ? buildAC(remote) : buildGeneric(remote, expanded));
  return card;
}
