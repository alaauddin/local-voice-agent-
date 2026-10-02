"use strict";

import { el } from "./dom.js";
import { state, fallback } from "./state.js";
import { setAvatar } from "./ui.js";
import { voiceController, VoicePhase } from "./voice-controller.js";
import { speakWithBrowser } from "./browser-speaker.js";

export function speakBrowser(text, done = () => {}, force = false) {
  window._activeKioskUtterance = speakWithBrowser({
    text,
    enabled: fallback.enabled,
    force,
    rate: fallback.rate,
    voiceURI: fallback.voiceURI,
    voices: fallback.voices,
    onStart: () => {
      voiceController.transition(VoicePhase.SPEAKING);
      setAvatar("speaking");
      el.voiceStatus.textContent = `${state.persona} يتحدث الآن…`;
    },
    onDone: done,
  });
}
