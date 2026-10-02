"use strict";

export function getBrowserVoices() {
  return window.speechSynthesis?.getVoices() || [];
}

export function speakWithBrowser({
  text,
  enabled,
  force = false,
  rate = 1,
  voiceURI = "",
  voices = [],
  onStart = () => {},
  onDone = () => {},
}) {
  if ((!force && !enabled) || !window.speechSynthesis || !text.trim()) {
    onDone();
    return null;
  }
  const utterance = new SpeechSynthesisUtterance(text.replace(/[*_#`\[\]]/g, ""));
  utterance.rate = rate;
  utterance.lang = /[\u0600-\u06ff]/.test(text) ? "ar-SA" : "en-US";
  const voice = voices.find((item) => item.voiceURI === voiceURI);
  if (voice) utterance.voice = voice;
  utterance.onstart = onStart;
  utterance.onend = onDone;
  utterance.onerror = onDone;
  window.speechSynthesis.speak(utterance);
  return utterance;
}
