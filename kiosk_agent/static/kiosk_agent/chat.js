(() => {
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
    browserVoice: $("#browserVoice"), speechRate: $("#speechRate"),
    speechRateValue: $("#speechRateValue"), testVoice: $("#testVoice"),
    messagesDrawer: $("#messagesDrawer"), messagesToggle: $("#messagesToggle"),
    closeMessages: $("#closeMessages"), messageCount: $("#messageCount"),
  };

  const wakeWord = ($('meta[name="voice-wake-word"]')?.content || "يا غروب").trim();
  const realtimeEnabled = $('meta[name="voice-source"]')?.content === "realtime";
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
  };
  const fallback = {
    enabled: localStorage.getItem("voiceFallbackEnabled") !== "false",
    voiceURI: localStorage.getItem("voiceFallbackURI") || "",
    rate: Number.parseFloat(localStorage.getItem("voiceFallbackRate") || "1.1"),
    voices: [],
  };
  const apiKey = localStorage.getItem("kioskApiKey") || "";
  const playback = new Audio();
  playback.preload = "auto";
  playback.volume = 1;

  async function unlockAudio() {
    if (state.audioUnlocked) return;
    try {
      // A short silent WAV started from a user gesture unlocks later streamed
      // playback in browsers that enforce media autoplay restrictions.
      playback.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAACA";
      await playback.play();
      playback.pause();
      playback.currentTime = 0;
      state.audioUnlocked = true;
    } catch (error) {
      console.debug("Audio unlock is waiting for a user gesture", error);
    }
  }

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

  function sendRealtime(event) {
    if (!state.rtcChannel || state.rtcChannel.readyState !== "open") return false;
    state.rtcChannel.send(JSON.stringify(event));
    return true;
  }

  function noteFirstAudioLatency() {
    if (!state.turnStoppedAt) return;
    console.debug(
      `Realtime first-audio latency: ${Math.round(performance.now() - state.turnStoppedAt)}ms`,
    );
    state.turnStoppedAt = 0;
  }

  function persistRealtimeMessage(role, content, eventId, inputMode = "realtime") {
    const clean = (content || "").trim();
    if (!clean || !state.currentRequestId) return Promise.resolve();
    return postJson("/api/v1/kiosk/realtime/messages/", {
      request_id: state.currentRequestId,
      role,
      content: clean,
      event_id: eventId || uuid(),
      input_mode: inputMode,
    }).catch((error) => console.error("Unable to persist realtime message", error));
  }

  function normalizeArabic(value) {
    return value
      .toLowerCase()
      .replace(/[\u064B-\u065F\u0670]/g, "")
      .replace(/ـ/g, "")
      .replace(/[إأآ]/g, "ا")
      .replace(/ى/g, "ي")
      .replace(/[^؀-ۿa-z0-9\s]/gi, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  const normalizedWakeWord = normalizeArabic(wakeWord);
  const endConversationPhrases = [
    "انهاء المحادثه", "انهي المحادثه", "مع السلامه", "خلاص شكرا", "شكرا غروب",
  ];

  function setAvatar(mode, force = false) {
    const videoMode = ["thinking", "speaking"].includes(mode) ? mode : "idle";
    if (!force && el.avatar.dataset.state === videoMode) return;
    el.avatar.dataset.state = videoMode;
    el.avatar.querySelectorAll(".avatar-video").forEach((video) => {
      const active = video.dataset.avatarState === videoMode;
      video.classList.toggle("active", active);
      if (active) {
        try { video.currentTime = 0; } catch (error) { console.debug(error); }
        video.play().catch(() => {});
      } else {
        video.pause();
        try { video.currentTime = 0; } catch (error) { console.debug(error); }
      }
    });
  }

  function updateControls() {
    el.send.disabled = !state.connected || (!realtimeEnabled && state.busy) || !el.input.value.trim();
    el.mic.disabled = !state.connected
      || (!realtimeEnabled && state.busy)
      || (!realtimeEnabled && !state.recognition);
    el.mic.classList.toggle("wake-armed", state.wakeArmed && state.recognitionMode === "wake");
    el.mic.classList.toggle("listening", state.recognitionMode === "command" && state.recognizing);
    el.mic.classList.toggle("conversation-active", state.conversationActive);
  }

  function setConnection(mode, text) {
    state.connected = mode === "online";
    el.connectionPill.classList.toggle("online", mode === "online");
    el.connectionPill.classList.toggle("offline", mode === "offline");
    el.mobileStatus.classList.toggle("online", mode === "online");
    el.connectionText.textContent = text;
    updateControls();
    if (state.connected && state.wakeArmed && !state.recognizing) scheduleWakeListener();
  }

  function setBusy(busy, text = "يجهّز لك الرد…") {
    state.busy = busy;
    el.activity.hidden = !busy;
    el.activityText.textContent = text;
    el.input.disabled = busy && !realtimeEnabled;
    if (busy) {
      stopRecognition();
      setAvatar("thinking");
      el.voiceStatus.textContent = text;
    }
    updateControls();
  }

  function scrollBottom() {
    requestAnimationFrame(() => { el.messages.scrollTop = el.messages.scrollHeight; });
  }

  function setMessagesOpen(open) {
    state.messagesOpen = open;
    el.messagesDrawer.classList.toggle("open", open);
    el.messagesDrawer.setAttribute("aria-hidden", String(!open));
    el.messagesToggle.setAttribute("aria-expanded", String(open));
    if (open) {
      state.unreadMessages = 0;
      el.messageCount.hidden = true;
      scrollBottom();
      el.closeMessages.focus();
    }
  }

  function noteNewMessage() {
    if (state.messagesOpen || state.loadingMemory) return;
    state.unreadMessages += 1;
    el.messageCount.textContent = String(Math.min(state.unreadMessages, 99));
    el.messageCount.hidden = false;
  }

  function createMessage(role, content = "", requestId = "") {
    const row = document.createElement("article");
    row.className = `message-row ${role}`;
    if (requestId) row.dataset.requestId = requestId;
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.dir = "auto";
    if (role === "assistant") {
      const label = document.createElement("span");
      label.className = "message-label";
      label.textContent = state.persona;
      const body = document.createElement("span");
      body.className = "message-content";
      body.textContent = content;
      bubble.append(label, body);
    } else {
      bubble.textContent = content;
    }
    row.append(bubble);
    el.messages.append(row);
    noteNewMessage();
    scrollBottom();
    return role === "assistant" ? bubble.querySelector(".message-content") : bubble;
  }

  function streamFor(requestId) {
    if (!state.streams.has(requestId)) state.streams.set(requestId, createMessage("assistant", "", requestId));
    return state.streams.get(requestId);
  }

  async function loadMemory() {
    try {
      const response = await fetch("/api/v1/kiosk/messages/", { headers: headers() });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      state.persona = data.chalet.persona_name || "غروب";
      el.chaletName.textContent = data.chalet.chalet_name || "الشاليه";
      el.personaIntro.textContent = `مرحباً بك، أنا ${state.persona}، كونسيرجك الرقمي الخاص.`;
      el.mobilePersona.textContent = state.persona;
      if (data.chalet.welcome_message) el.welcomeMessage.textContent = data.chalet.welcome_message;
      state.loadingMemory = true;
      data.messages.forEach((message) => createMessage(message.role, message.content, message.request_id));
      state.loadingMemory = false;
      if (data.messages.some((message) => message.role === "user" && ["queued", "streaming"].includes(message.status))) {
        setBusy(true, "جارٍ استكمال طلبك…");
      }
    } catch (error) {
      console.error("Unable to load kiosk memory", error);
    }
  }

  function connect() {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const key = apiKey ? `?key=${encodeURIComponent(apiKey)}` : "";
    state.socket = new WebSocket(`${protocol}://${location.host}/ws/kiosk/${key}`);
    setConnection("connecting", "جاري الاتصال…");
    state.socket.addEventListener("open", () => {
      state.reconnectAttempts = 0;
      setConnection("online", "متصل وجاهز لخدمتك");
    });
    state.socket.addEventListener("message", ({ data }) => {
      try { handleEvent(JSON.parse(data)); } catch (error) { console.error("Invalid socket event", error); }
    });
    state.socket.addEventListener("close", () => {
      setConnection("offline", "انقطع الاتصال — نحاول مجدداً");
      if (state.shouldReconnect) {
        const delay = Math.min(1000 * (2 ** state.reconnectAttempts++), 10000);
        window.setTimeout(connect, delay);
      }
    });
    state.socket.addEventListener("error", () => state.socket.close());
  }

  function handleEvent(event) {
    const requestId = event.request_id || "current";
    switch (event.event) {
      case "accepted": setBusy(true); break;
      case "status": setBusy(true, event.status === "thinking" ? "يفكر في أفضل طريقة لخدمتك…" : "يجهّز لك الرد…"); break;
      case "token":
        streamFor(requestId).textContent += event.token;
        scrollBottom();
        break;
      case "tool_status": setBusy(true, event.status === "running" ? "يرتّب طلبك الآن…" : "تم ترتيب الطلب…"); break;
      case "complete": {
        const target = streamFor(requestId);
        if (!target.textContent) target.textContent = event.content || "تمت خدمتك بكل سرور.";
        state.streams.delete(requestId);
        setBusy(true, "يحضّر الرد الصوتي…");
        clearTimeout(state.completionTimer);
        state.completionTimer = window.setTimeout(finishTurn, 4000);
        break;
      }
      case "tts_status":
        clearTimeout(state.completionTimer);
        resetAudio(event.nonce, event.total);
        setBusy(true, "يحضّر الرد الصوتي…");
        break;
      case "tts_audio": receiveChunk(event); break;
      case "tts_chunk_fallback": receiveChunk({ ...event, fallbackText: event.text }); break;
      case "tts_fallback":
        resetAudio(event.nonce, 1);
        receiveChunk({ ...event, seq: 0, total: 1, fallbackText: event.text });
        state.ttsEnded = true;
        playNext();
        break;
      case "tts_end":
        state.ttsEnded = true;
        playNext();
        break;
      case "busy": setBusy(true, event.message || "يوجد طلب قيد التنفيذ…"); break;
      case "error":
        createMessage("assistant", event.message || "تعذر إكمال الطلب حالياً. يرجى المحاولة مرة أخرى.");
        finishTurn();
        break;
      case "cancelled": finishTurn(); break;
      case "reset":
        closeRealtime();
        state.conversationActive = false;
        restartSocket();
        break;
      default: break;
    }
  }

  function resetAudio(nonce, total = 0) {
    stopAudio();
    state.activeNonce = nonce;
    state.audioBuffer = new Map();
    state.nextSeq = 0;
    state.totalSeq = total || 0;
    state.ttsEnded = false;
  }

  function receiveChunk(event) {
    if (state.activeNonce && event.nonce !== state.activeNonce) return;
    if (!state.activeNonce) resetAudio(event.nonce, event.total);
    state.totalSeq = event.total || state.totalSeq;
    state.audioBuffer.set(event.seq, event.fallbackText
      ? { type: "speech", value: event.fallbackText }
      : {
          type: "audio",
          value: `data:${event.content_type || "audio/mpeg"};base64,${event.audio}`,
          fallbackText: event.text || "",
        });
    playNext();
  }

  function playNext() {
    if (state.audioPlaying) return;
    const chunk = state.audioBuffer.get(state.nextSeq);
    if (!chunk) {
      if (state.ttsEnded && state.nextSeq >= state.totalSeq) finishTurn();
      return;
    }
    state.audioBuffer.delete(state.nextSeq);
    state.audioPlaying = true;
    setAvatar("speaking");
    el.voiceStatus.textContent = `${state.persona} يتحدث الآن…`;
    if (chunk.type === "speech") {
      speakBrowser(chunk.value, chunkFinished, true);
      return;
    }
    const audio = playback;
    audio.src = chunk.value;
    audio.muted = false;
    audio.volume = 1;
    state.activeAudio = audio;
    let settled = false;
    const finishOnce = () => {
      if (settled) return;
      settled = true;
      chunkFinished();
    };
    audio.onended = finishOnce;
    const useFallback = () => {
      if (settled) return;
      settled = true;
      audio.onended = null;
      audio.onerror = null;
      state.activeAudio = null;
      console.warn("Server audio could not be played; using browser speech fallback");
      if (chunk.fallbackText) speakBrowser(chunk.fallbackText, chunkFinished, true);
      else chunkFinished();
    };
    audio.onerror = useFallback;
    audio.play().then(() => { state.audioUnlocked = true; }).catch(useFallback);
  }

  function chunkFinished() {
    state.audioPlaying = false;
    state.activeAudio = null;
    state.nextSeq += 1;
    playNext();
  }

  function stopAudio() {
    if (state.activeAudio) {
      state.activeAudio.pause();
      state.activeAudio.src = "";
    }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    state.activeAudio = null;
    state.audioPlaying = false;
    state.audioBuffer.clear();
  }

  function extractResponseTranscript(response) {
    return (response?.output || []).flatMap((item) => item.content || [])
      .map((part) => part.transcript || part.text || "")
      .join("")
      .trim();
  }

  async function runRealtimeTools(calls) {
    if (!state.currentRequestId) state.currentRequestId = uuid();
    for (const call of calls) {
      state.toolIterations += 1;
      setBusy(true, "يرتّب طلبك الآن…");
      let output;
      if (state.toolIterations > 5) {
        output = { ok: false, error: "tool_iteration_limit" };
      } else {
        try {
          output = await postJson("/api/v1/kiosk/realtime/tools/", {
            request_id: state.currentRequestId,
            call_id: call.call_id,
            name: call.name,
            arguments: JSON.parse(call.arguments || "{}"),
          });
        } catch (error) {
          output = { ok: false, error: "tool_execution_failed" };
          console.error("Realtime tool failed", error);
        }
      }
      sendRealtime({
        type: "conversation.item.create",
        item: {
          type: "function_call_output",
          call_id: call.call_id,
          output: JSON.stringify(output),
        },
      });
    }
    sendRealtime({ type: "response.create" });
  }

  async function handleRealtimeEvent(event) {
    switch (event.type) {
      case "session.created":
      case "session.updated":
        return;
      case "input_audio_buffer.speech_started":
        // Cut the assistant audio locally before its tail can leak back into the
        // microphone. Server VAD still handles cancelling the active response.
        playback.muted = true;
        state.outputAudioActive = false;
        state.responseComplete = false;
        state.currentRequestId = uuid();
        state.toolIterations = 0;
        state.assistantTranscript = "";
        state.assistantTarget = null;
        touchConversationTimeout();
        setBusy(false);
        setAvatar("idle");
        el.voiceStatus.textContent = "أنا أسمعك…";
        return;
      case "input_audio_buffer.speech_stopped":
        state.turnStoppedAt = performance.now();
        setBusy(true, "فهمت عليك…");
        return;
      case "conversation.item.input_audio_transcription.delta":
        el.interim.textContent += event.delta || "";
        return;
      case "conversation.item.input_audio_transcription.completed": {
        const transcript = (event.transcript || "").trim();
        el.interim.textContent = "";
        if (transcript) {
          createMessage("user", transcript, state.currentRequestId);
          await persistRealtimeMessage("user", transcript, event.item_id, "voice");
        }
        return;
      }
      case "response.created":
        state.responseStartedAt = performance.now();
        state.responseComplete = false;
        setBusy(true, "غروب معك…");
        return;
      case "output_audio_buffer.started":
        noteFirstAudioLatency();
        playback.muted = false;
        state.outputAudioActive = true;
        setBusy(false);
        setAvatar("speaking");
        el.voiceStatus.textContent = `${state.persona} يتحدث الآن… قاطعه متى شئت`;
        return;
      case "output_audio_buffer.stopped":
      case "output_audio_buffer.cleared":
        state.outputAudioActive = false;
        if (state.responseComplete) {
          setAvatar("idle");
          el.voiceStatus.textContent = "تفضل… أنا أستمع";
        }
        return;
      case "response.output_audio.delta":
      case "response.audio.delta":
        noteFirstAudioLatency();
        playback.muted = false;
        setBusy(false);
        setAvatar("speaking");
        el.voiceStatus.textContent = `${state.persona} يتحدث الآن… قاطعه متى شئت`;
        return;
      case "response.output_audio_transcript.delta":
      case "response.audio_transcript.delta": {
        if (!state.currentRequestId) state.currentRequestId = uuid();
        if (!state.assistantTarget) {
          state.assistantTarget = createMessage("assistant", "", state.currentRequestId);
        }
        const delta = event.delta || "";
        state.assistantTranscript += delta;
        state.assistantTarget.textContent += delta;
        scrollBottom();
        return;
      }
      case "response.output_audio_transcript.done":
      case "response.audio_transcript.done":
        if (event.transcript) state.assistantTranscript = event.transcript;
        state.assistantEventId = event.item_id || event.response_id || uuid();
        return;
      case "response.done": {
        state.responseComplete = true;
        const calls = (event.response?.output || []).filter((item) => item.type === "function_call");
        if (calls.length) {
          await runRealtimeTools(calls);
          return;
        }
        const transcript = state.assistantTranscript || extractResponseTranscript(event.response);
        if (transcript) {
          if (!state.assistantTarget) {
            state.assistantTarget = createMessage("assistant", transcript, state.currentRequestId);
          } else if (!state.assistantTarget.textContent) {
            state.assistantTarget.textContent = transcript;
          }
          await persistRealtimeMessage(
            "assistant", transcript, state.assistantEventId || event.response?.id, "realtime",
          );
        }
        state.assistantTranscript = "";
        state.assistantTarget = null;
        state.assistantEventId = "";
        setBusy(false);
        if (!state.outputAudioActive) setAvatar("idle");
        el.voiceStatus.textContent = "تفضل… أنا أستمع";
        touchConversationTimeout();
        return;
      }
      case "error":
        console.error("OpenAI Realtime error", event.error || event);
        setBusy(false);
        el.voiceStatus.textContent = "تعذر إكمال الرد، تفضل بالمحاولة مرة أخرى";
        return;
      default:
        return;
    }
  }

  function closeRealtime() {
    state.realtimeReady = false;
    if (state.rtcChannel) state.rtcChannel.close();
    if (state.rtcPeer) state.rtcPeer.close();
    if (state.rtcStream) state.rtcStream.getTracks().forEach((track) => track.stop());
    if (playback.srcObject) {
      playback.pause();
      playback.srcObject = null;
    }
    state.rtcChannel = null;
    state.rtcPeer = null;
    state.rtcStream = null;
    state.currentRequestId = null;
    state.assistantTranscript = "";
    state.assistantTarget = null;
    state.outputAudioActive = false;
    state.responseComplete = false;
  }

  async function startRealtime(initialText = "") {
    if (!realtimeEnabled || state.realtimeReady || state.rtcPeer) return;
    stopRecognition();
    state.conversationActive = true;
    touchConversationTimeout();
    setBusy(true, "أتصل بغروب…");
    const connectionStartedAt = performance.now();
    try {
      const supportedConstraints = navigator.mediaDevices.getSupportedConstraints?.() || {};
      const audioConstraints = {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      };
      if (supportedConstraints.voiceIsolation) audioConstraints.voiceIsolation = true;
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: audioConstraints,
      });
      const microphoneTrack = stream.getAudioTracks()[0];
      if (microphoneTrack) {
        console.debug("Microphone processing", microphoneTrack.getSettings());
      }
      const pc = new RTCPeerConnection();
      const dc = pc.createDataChannel("oai-events");
      state.rtcPeer = pc;
      state.rtcChannel = dc;
      state.rtcStream = stream;
      stream.getAudioTracks().forEach((track) => pc.addTrack(track, stream));
      pc.ontrack = ({ streams }) => {
        playback.srcObject = streams[0];
        playback.muted = false;
        playback.volume = 1;
        playback.play().catch((error) => console.error("Realtime audio playback failed", error));
      };
      dc.addEventListener("message", ({ data }) => {
        try { handleRealtimeEvent(JSON.parse(data)).catch((error) => console.error(error)); }
        catch (error) { console.error("Invalid Realtime event", error); }
      });
      const channelReady = new Promise((resolve, reject) => {
        dc.addEventListener("open", resolve, { once: true });
        dc.addEventListener("error", reject, { once: true });
      });
      pc.addEventListener("connectionstatechange", () => {
        if (["failed", "closed"].includes(pc.connectionState) && state.conversationActive) {
          endConversation(false);
        }
      });
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      const realtimeHeaders = { "Content-Type": "application/sdp" };
      if (apiKey) realtimeHeaders["X-Kiosk-Key"] = apiKey;
      const response = await fetch("/api/v1/kiosk/realtime/session/", {
        method: "POST", headers: realtimeHeaders, body: offer.sdp,
      });
      if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
      await pc.setRemoteDescription({ type: "answer", sdp: await response.text() });
      await channelReady;
      console.debug(
        `Realtime connection latency: ${Math.round(performance.now() - connectionStartedAt)}ms`,
      );
      state.realtimeReady = true;
      state.currentRequestId = uuid();
      state.toolIterations = 0;
      if (initialText.trim()) {
        const clean = initialText.trim();
        createMessage("user", clean, state.currentRequestId);
        await persistRealtimeMessage("user", clean, `typed-${state.currentRequestId}`, "voice");
        sendRealtime({
          type: "conversation.item.create",
          item: { type: "message", role: "user", content: [{ type: "input_text", text: clean }] },
        });
        sendRealtime({ type: "response.create" });
      } else {
        sendRealtime({
          type: "response.create",
          response: {
            instructions: "رحّب بالضيف الآن بجملة عربية قصيرة ودافئة جداً، ثم قل له: تفضل، أنا معك.",
          },
        });
      }
      setBusy(false);
      el.voiceStatus.textContent = "تفضل… أنا أستمع";
    } catch (error) {
      console.error("Unable to start Realtime", error);
      closeRealtime();
      state.conversationActive = false;
      setBusy(false);
      speakBrowser("تعذر تشغيل المحادثة المباشرة الآن. حاول مرة أخرى.", () => {
        scheduleWakeListener(500);
      }, true);
    }
  }

  function finishTurn() {
    clearTimeout(state.completionTimer);
    setBusy(false);
    setAvatar("idle");
    if (state.conversationActive && realtimeEnabled) {
      el.voiceStatus.textContent = "تفضل… أنا أستمع";
      touchConversationTimeout();
    } else if (state.conversationActive) {
      el.voiceStatus.textContent = "تفضل… أنا أستمع";
      touchConversationTimeout();
      window.setTimeout(() => startRecognition("command"), 450);
    } else {
      el.voiceStatus.textContent = state.wakeArmed
        ? `قل «${wakeWord}» لبدء المحادثة`
        : `اضغط على الميكروفون للسماح بالاستماع`;
      if (state.wakeArmed) scheduleWakeListener(500);
    }
  }

  function touchConversationTimeout() {
    clearTimeout(state.inactivityTimer);
    if (!state.conversationActive) return;
    state.inactivityTimer = window.setTimeout(() => endConversation(false), 120000);
  }

  function endConversation(sayGoodbye = true) {
    clearTimeout(state.inactivityTimer);
    state.conversationActive = false;
    state.pendingCommand = false;
    if (realtimeEnabled) closeRealtime();
    stopRecognition();
    el.interim.textContent = "";
    setAvatar("idle");
    el.voiceStatus.textContent = `قل «${wakeWord}» لبدء محادثة جديدة`;
    updateControls();
    const resumeWake = () => scheduleWakeListener(350);
    if (sayGoodbye) speakBrowser("في أمان الله، أنا هنا متى احتجتني", resumeWake);
    else resumeWake();
  }

  function speakBrowser(text, done = () => {}, force = false) {
    if ((!force && !fallback.enabled) || !window.speechSynthesis || !text.trim()) { done(); return; }
    const utterance = new SpeechSynthesisUtterance(text.replace(/[*_#`\[\]]/g, ""));
    utterance.rate = fallback.rate;
    utterance.lang = /[\u0600-\u06ff]/.test(text) ? "ar-SA" : "en-US";
    const voice = fallback.voices.find((item) => item.voiceURI === fallback.voiceURI);
    if (voice) utterance.voice = voice;
    utterance.onend = done;
    utterance.onerror = done;
    window._activeKioskUtterance = utterance;
    window.speechSynthesis.speak(utterance);
  }

  function configureRecognition() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      el.voiceStatus.textContent = "التعرف الصوتي غير مدعوم، يمكنك الكتابة أدناه";
      return;
    }
    state.recognition = new Recognition();
    state.recognition.interimResults = true;
    state.recognition.lang = "ar-SA";
    state.recognition.onstart = () => {
      state.recognizing = true;
      if (state.recognitionMode === "wake") {
        setAvatar("idle");
        el.voiceStatus.textContent = `جاهز — قل «${wakeWord}»`;
      } else {
        setAvatar("idle");
        el.voiceStatus.textContent = "نعم، تفضل… أنا أستمع";
      }
      updateControls();
    };
    state.recognition.onresult = recognitionResult;
    state.recognition.onerror = recognitionError;
    state.recognition.onend = recognitionEnded;
    state.wakeArmed = true;
    updateControls();
  }

  function recognitionResult(event) {
    let interim = "";
    let finalText = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const transcript = event.results[index][0].transcript;
      if (event.results[index].isFinal) finalText += transcript;
      else interim += transcript;
    }
    const heard = `${finalText} ${interim}`.trim();
    el.interim.textContent = heard;
    if (
      state.recognitionMode === "wake"
      && finalText.trim()
      && normalizeArabic(finalText).includes(normalizedWakeWord)
    ) {
      const exactIndex = finalText.indexOf(wakeWord);
      const remainder = exactIndex >= 0 ? finalText.slice(exactIndex + wakeWord.length).trim() : "";
      state.pendingCommand = false;
      state.finalHandled = Boolean(remainder);
      state.conversationActive = true;
      touchConversationTimeout();
      stopRecognition();
      if (realtimeEnabled) {
        el.interim.textContent = "";
        startRealtime(remainder);
      } else if (remainder) submitMessage(remainder, true);
      else {
        el.interim.textContent = "";
        setAvatar("speaking");
        el.voiceStatus.textContent = `${state.persona} يرحّب بك…`;
        speakBrowser("أهلاً وسهلاً، أنا معك. تفضل.", () => {
          if (!state.conversationActive || state.busy) return;
          setAvatar("idle");
          el.voiceStatus.textContent = "تفضل… أنا أستمع";
          startRecognition("command");
        }, true);
      }
      return;
    }
    if (!realtimeEnabled && state.recognitionMode === "command" && finalText.trim() && !state.finalHandled) {
      const normalizedFinal = normalizeArabic(finalText);
      if (endConversationPhrases.some((phrase) => normalizedFinal.includes(phrase))) {
        state.finalHandled = true;
        stopRecognition();
        endConversation(true);
        return;
      }
      state.finalHandled = true;
      stopRecognition();
      submitMessage(finalText, true);
    }
  }

  function recognitionError(event) {
    state.recognizing = false;
    if (["not-allowed", "service-not-allowed"].includes(event.error)) {
      state.wakeArmed = false;
      el.voiceStatus.textContent = "يرجى السماح باستخدام الميكروفون";
    } else if (state.recognitionMode === "command") {
      el.voiceStatus.textContent = state.conversationActive
        ? "ما زلت معك… تفضل"
        : `قل «${wakeWord}» لبدء المحادثة`;
    }
    updateControls();
  }

  function recognitionEnded() {
    const endedMode = state.recognitionMode;
    state.recognizing = false;
    state.recognitionMode = null;
    updateControls();
    if (state.pendingCommand) {
      state.pendingCommand = false;
      window.setTimeout(() => startRecognition("command"), 180);
    } else if (endedMode === "wake" && state.wakeArmed && !state.conversationActive && !state.busy) {
      scheduleWakeListener(400);
    } else if (!realtimeEnabled && endedMode === "command" && !state.finalHandled && state.conversationActive && !state.busy) {
      window.setTimeout(() => startRecognition("command"), 400);
    }
  }

  function startRecognition(mode) {
    if (!state.recognition || state.recognizing || state.busy || !state.connected) return;
    state.recognitionMode = mode;
    state.finalHandled = false;
    state.recognition.continuous = mode === "wake";
    try { state.recognition.start(); } catch (error) { console.debug("Recognition start delayed", error); }
  }

  function stopRecognition() {
    if (!state.recognition || !state.recognizing) return;
    try { state.recognition.stop(); } catch (error) { console.debug("Recognition already stopped", error); }
  }

  function scheduleWakeListener(delay = 250) {
    if (!state.wakeArmed || state.conversationActive || state.busy || state.recognizing || !state.connected) return;
    window.setTimeout(() => {
      if (state.wakeArmed && !state.conversationActive && !state.busy && !state.recognizing) startRecognition("wake");
    }, delay);
  }

  function toggleWakeWord() {
    if (state.conversationActive) {
      endConversation(false);
    } else if (realtimeEnabled) {
      state.wakeArmed = true;
      stopRecognition();
      startRealtime();
    } else if (state.wakeArmed && state.recognizing) {
      state.conversationActive = true;
      state.pendingCommand = true;
      stopRecognition();
      touchConversationTimeout();
      el.voiceStatus.textContent = "تفضل… أنا أستمع";
    } else {
      state.wakeArmed = true;
      el.voiceStatus.textContent = `جارٍ تفعيل «${wakeWord}»…`;
      startRecognition("wake");
    }
    updateControls();
  }

  async function submitMessage(message, fromVoice = false) {
    const clean = message.trim();
    if (!clean || !state.connected || (!realtimeEnabled && state.busy)) return;
    if (fromVoice) touchConversationTimeout();
    el.input.value = "";
    el.interim.textContent = "";
    resizeInput();
    if (realtimeEnabled) {
      if (!state.realtimeReady) {
        await startRealtime(clean);
        return;
      }
      state.currentRequestId = uuid();
      state.toolIterations = 0;
      createMessage("user", clean, state.currentRequestId);
      await persistRealtimeMessage("user", clean, `text-${state.currentRequestId}`, "text");
      if (state.busy) sendRealtime({ type: "response.cancel" });
      sendRealtime({
        type: "conversation.item.create",
        item: { type: "message", role: "user", content: [{ type: "input_text", text: clean }] },
      });
      sendRealtime({ type: "response.create" });
      setBusy(true, "غروب معك…");
      return;
    }
    createMessage("user", clean);
    setBusy(true);
    state.socket.send(JSON.stringify({ type: "chat.message", message: clean, input_mode: fromVoice ? "voice" : "text" }));
  }

  function resizeInput() {
    el.input.style.height = "auto";
    el.input.style.height = `${Math.min(el.input.scrollHeight, 140)}px`;
    updateControls();
  }

  function populateVoices() {
    if (!window.speechSynthesis) return;
    fallback.voices = window.speechSynthesis.getVoices();
    el.browserVoice.replaceChildren();
    [...fallback.voices]
      .sort((a, b) => Number(b.lang.startsWith("ar")) - Number(a.lang.startsWith("ar")))
      .forEach((voice) => {
        const option = document.createElement("option");
        option.value = voice.voiceURI;
        option.textContent = `${voice.name} (${voice.lang})`;
        option.selected = voice.voiceURI === fallback.voiceURI;
        el.browserVoice.append(option);
      });
  }

  function restartSocket() {
    state.shouldReconnect = false;
    if (state.socket) state.socket.close();
    window.setTimeout(() => { state.shouldReconnect = true; connect(); }, 150);
  }

  async function resetStay() {
    el.confirmReset.disabled = true;
    stopRecognition();
    stopAudio();
    closeRealtime();
    try {
      const response = await fetch("/api/v1/kiosk/reset/", { method: "POST", headers: headers(), body: "{}" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      el.messages.querySelectorAll(".message-row").forEach((node) => node.remove());
      state.unreadMessages = 0;
      el.messageCount.hidden = true;
      setMessagesOpen(false);
      state.streams.clear();
      finishTurn();
      el.resetDialog.close();
      restartSocket();
    } catch (error) {
      el.confirmReset.disabled = false;
      el.confirmReset.textContent = "تعذر المسح — حاول مجدداً";
    }
  }

  el.form.addEventListener("submit", (event) => { event.preventDefault(); submitMessage(el.input.value); });
  document.addEventListener("pointerdown", unlockAudio, { once: true, passive: true });
  document.addEventListener("keydown", unlockAudio, { once: true });
  el.input.addEventListener("input", resizeInput);
  el.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submitMessage(el.input.value); }
  });
  $("#suggestions").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-message]");
    if (button) submitMessage(button.dataset.message);
  });
  el.mic.addEventListener("click", toggleWakeWord);
  el.messagesToggle.addEventListener("click", () => setMessagesOpen(!state.messagesOpen));
  el.closeMessages.addEventListener("click", () => setMessagesOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.messagesOpen) setMessagesOpen(false);
  });
  el.reset.addEventListener("click", () => el.resetDialog.showModal());
  el.cancelReset.addEventListener("click", () => el.resetDialog.close());
  el.confirmReset.addEventListener("click", resetStay);
  el.settingsButton.addEventListener("click", () => el.settingsDialog.showModal());
  el.closeSettings.addEventListener("click", () => el.settingsDialog.close());
  el.fallbackEnabled.checked = fallback.enabled;
  el.speechRate.value = fallback.rate;
  el.speechRateValue.textContent = fallback.rate.toFixed(1);
  el.fallbackEnabled.addEventListener("change", () => {
    fallback.enabled = el.fallbackEnabled.checked;
    localStorage.setItem("voiceFallbackEnabled", String(fallback.enabled));
  });
  el.browserVoice.addEventListener("change", () => {
    fallback.voiceURI = el.browserVoice.value;
    localStorage.setItem("voiceFallbackURI", fallback.voiceURI);
  });
  el.speechRate.addEventListener("input", () => {
    fallback.rate = Number.parseFloat(el.speechRate.value);
    el.speechRateValue.textContent = fallback.rate.toFixed(1);
    localStorage.setItem("voiceFallbackRate", String(fallback.rate));
  });
  el.testVoice.addEventListener("click", () => speakBrowser("أهلاً وسهلاً بك، أنا غروب وفي خدمتك"));
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopRecognition();
      if (realtimeEnabled && state.conversationActive) endConversation(false);
      return;
    }
    if (!state.connected || state.busy) return;
    if (state.conversationActive && !realtimeEnabled) window.setTimeout(() => startRecognition("command"), 250);
    else scheduleWakeListener(250);
  });
  window.addEventListener("beforeunload", () => { stopRecognition(); closeRealtime(); });
  if (window.speechSynthesis) {
    populateVoices();
    window.speechSynthesis.onvoiceschanged = populateVoices;
  }

  setAvatar("idle", true);
  configureRecognition();
  loadMemory();
  connect();
})();
