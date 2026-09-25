"use strict";

import { apiKey } from "./config.js";

function headers() {
  const result = { "Content-Type": "application/json" };
  if (apiKey) result["X-Kiosk-Key"] = apiKey;
  return result;
}

function uuid() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST", headers: headers(), body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || `HTTP ${response.status}`);
  return data;
}

async function patchJson(url, payload) {
  const response = await fetch(url, {
    method: "PATCH", headers: headers(), body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || `HTTP ${response.status}`);
  return data;
}

export { headers, uuid, postJson, patchJson };
