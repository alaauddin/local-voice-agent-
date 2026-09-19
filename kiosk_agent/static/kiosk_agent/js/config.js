"use strict";

const meta = (name) => document.querySelector(`meta[name="${name}"]`)?.content;

export const wakeWord = (meta("voice-wake-word") || "يا غروب").trim();
export const voiceSource = meta("voice-source") || "realtime";
export const realtimeEnabled = voiceSource === "realtime";
export const activationMode = meta("voice-activation-mode") || "wake";
export const apiKey = "";
