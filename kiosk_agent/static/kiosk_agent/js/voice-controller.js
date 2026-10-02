"use strict";

export const VoicePhase = Object.freeze({
  IDLE: "idle",
  CONNECTING: "connecting",
  LISTENING: "listening",
  PROCESSING: "processing",
  SPEAKING: "speaking",
  RECOVERING: "recovering",
  STOPPED: "stopped",
});

class VoiceController {
  constructor() {
    this.phase = VoicePhase.IDLE;
    this.generation = 0;
    this.handlers = {};
    this.timers = new Map();
    this.diagnostics = [];
  }

  configure(handlers) {
    this.handlers = { ...this.handlers, ...handlers };
  }

  call(name, ...args) {
    const handler = this.handlers[name];
    if (!handler) {
      console.warn(`[Voice] handler is not configured: ${name}`);
      return undefined;
    }
    return handler(...args);
  }

  transition(phase, detail = {}) {
    const previous = this.phase;
    this.phase = phase;
    this.diagnostics.push({
      at: Date.now(), generation: this.generation, previous, phase, ...detail,
    });
    if (this.diagnostics.length > 80) this.diagnostics.shift();
    console.debug("[Voice] state", { previous, phase, generation: this.generation, ...detail });
  }

  beginSession(detail = {}) {
    this.generation += 1;
    this.cancelAllTimers();
    this.transition(VoicePhase.CONNECTING, detail);
    return this.generation;
  }

  invalidateSession(detail = {}) {
    this.generation += 1;
    this.cancelAllTimers();
    this.transition(VoicePhase.STOPPED, detail);
    return this.generation;
  }

  isCurrent(generation) {
    return generation === this.generation;
  }

  assertCurrent(generation) {
    if (!this.isCurrent(generation)) throw new DOMException("Stale voice session", "AbortError");
  }

  schedule(name, callback, delay, generation = this.generation) {
    this.cancelTimer(name);
    const timer = window.setTimeout(() => {
      this.timers.delete(name);
      if (!this.isCurrent(generation)) return;
      callback();
    }, delay);
    this.timers.set(name, timer);
    return timer;
  }

  hasTimer(name) {
    return this.timers.has(name);
  }

  cancelTimer(name) {
    const timer = this.timers.get(name);
    if (timer) window.clearTimeout(timer);
    this.timers.delete(name);
  }

  cancelAllTimers() {
    this.timers.forEach((timer) => window.clearTimeout(timer));
    this.timers.clear();
  }
}

export const voiceController = new VoiceController();
