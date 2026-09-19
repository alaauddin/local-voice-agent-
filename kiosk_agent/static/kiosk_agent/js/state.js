"use strict";

import { activationMode } from "./config.js";

const state = {
  socket: null, connected: false, busy: false, persona: "غروب", streams: new Map(),
  reconnectAttempts: 0, shouldReconnect: true, recognition: null, recognitionMode: null,
  recognizing: false, wakeArmed: false, conversationActive: false,
  pendingCommand: false, finalHandled: false, inactivityTimer: null,
  activeNonce: null, audioBuffer: new Map(), nextSeq: 0, totalSeq: 0,
  audioPlaying: false, activeAudio: null, audioUnlocked: false,
  ttsEnded: false, completionTimer: null,
  messagesOpen: false, unreadMessages: 0, loadingMemory: false,
  rtcPeer: null, rtcChannel: null, rtcStream: null, realtimeReady: false,
  currentRequestId: null, assistantTranscript: "", assistantTarget: null,
  assistantEventId: "", toolIterations: 0, outputAudioActive: false,
  responseComplete: false, turnStoppedAt: 0, responseStartedAt: 0,
  micAutoStartEnabled: activationMode === "always_on", autoStartTimer: null,
  localSessionId: null, currentStayId: null, connectionPromise: null,
  realtimeRetryAttempts: 0,
  remotes: [], remoteIndex: 0, remotePressing: false, pendingRemoteButton: null,
};
const fallback = {
  enabled: localStorage.getItem("voiceFallbackEnabled") !== "false",
  voiceURI: localStorage.getItem("voiceFallbackURI") || "",
  rate: Number.parseFloat(localStorage.getItem("voiceFallbackRate") || "1.1"),
  voices: [],
};
export { state, fallback };
