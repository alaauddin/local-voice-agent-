"use strict";

const $ = (selector) => document.querySelector(selector);
const el = {
  messages: $("#messages"), welcome: $("#welcomeCard"), welcomeMessage: $("#welcomeMessage"),
  chaletName: $("#chaletName"), personaIntro: $("#personaIntro"), mobilePersona: $("#mobilePersona"),
  connectionPill: $("#connectionPill"), connectionText: $("#connectionText"), mobileStatus: $("#mobileStatus"),
  form: $("#chatForm"), input: $("#messageInput"), send: $("#sendButton"), activity: $("#activity"),
  activityText: $("#activityText"), mic: $("#micButton"), voiceStatus: $("#voiceStatus"),
  interim: $("#interimTranscript"), avatar: $("#avatarStage"), reset: $("#resetButton"),
  resetDialog: $("#resetDialog"), cancelReset: $("#cancelReset"), confirmReset: $("#confirmReset"),
  settingsButton: $("#voiceSettingsButton"), settingsDialog: $("#voiceSettingsDialog"),
  closeSettings: $("#closeVoiceSettings"), fallbackEnabled: $("#fallbackEnabled"),
  preferredMic: $("#preferredMic"), browserVoice: $("#browserVoice"), speechRate: $("#speechRate"),
  speechRateValue: $("#speechRateValue"), testVoice: $("#testVoice"),
  messagesDrawer: $("#messagesDrawer"), messagesToggle: $("#messagesToggle"),
  closeMessages: $("#closeMessages"), messageCount: $("#messageCount"),
  voiceStage: $("#voiceStage"), remotesPanel: $("#remotesPanel"),
  remotesCarousel: $("#remotesCarousel"), remotesTrack: $("#remotesTrack"),
  remoteDots: $("#remoteDots"), remotePrev: $("#remotePrev"), remoteNext: $("#remoteNext"),
  remoteTitle: $("#remoteTitle"), remoteLocation: $("#remoteLocation"),
  remoteFeedback: $("#remoteFeedback"), remoteConfirmDialog: $("#remoteConfirmDialog"),
  cancelRemoteConfirm: $("#cancelRemoteConfirm"), confirmRemotePress: $("#confirmRemotePress"),
  remoteConfirmTitle: $("#remoteConfirmTitle"), remoteConfirmText: $("#remoteConfirmText"),
};

export { $, el };
