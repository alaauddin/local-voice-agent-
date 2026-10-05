"use strict";

import { activationMode } from "./config.js";

const state = {
  socket: null, connected: false, busy: false, persona: "غروب", streams: new Map(),
  reconnectAttempts: 0, shouldReconnect: true, recognition: null, recognitionMode: null,
  recognizing: false, wakeArmed: false, conversationActive: false,
  recognitionStartedAt: 0, recognitionRestartAttempts: 0,
  pendingCommand: false, finalHandled: false,
  activeNonce: null, audioBuffer: new Map(), nextSeq: 0, totalSeq: 0,
  audioPlaying: false, activeAudio: null, audioUnlocked: false,
  ttsEnded: false,
  messagesOpen: false, unreadMessages: 0, loadingMemory: false,
  rtcPeer: null, rtcChannel: null, rtcStream: null, realtimeReady: false,
  currentRequestId: null, assistantTranscript: "", assistantTarget: null,
  assistantEventId: "", toolIterations: 0, outputAudioActive: false,
  responseComplete: false, turnStoppedAt: 0, responseStartedAt: 0,
  micAutoStartEnabled: activationMode === "always_on",
  localSessionId: null, currentStayId: null, connectionPromise: null,
  realtimeRetryAttempts: 0, realtimeGeneration: 0, realtimeAbortController: null, backendVoiceRequestId: null,
  remotes: [], remoteIndex: 0, remotePressing: false, pendingRemoteButton: null,
};
const fallback = {
  enabled: localStorage.getItem("voiceFallbackEnabled") !== "false",
  voiceURI: localStorage.getItem("voiceFallbackURI") || "",
  rate: Number.parseFloat(localStorage.getItem("voiceFallbackRate") || "1.1"),
  voices: [],
};
export { state, fallback };
