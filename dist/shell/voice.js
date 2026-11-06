import { Resampler, TARGET_RATE, floatToInt16, int16ToFloat, indicatorState, INDICATOR_TEXT, voiceSocketUrl, NO_RECONNECT_CODES } from "./voice-core.js";
import { normalizeRealtimeEvent } from "./realtime.js";

const FORWARDED = new Set(["turn.state", "transcript.partial", "assistant.delivered", "degraded", "ui.mic.ack"]);

// Hands-free microphone loop. The microphone is only open while this object says "listening":
// closing the curtain (paused) stops the tracks, which also clears the operating-system mic light.
export class VoiceLoop {
  constructor({ deliver, audioBands, win = window, doc = document } = {}) {
    this.deliver = deliver || (() => {});
    this.audioBands = audioBands;
    this.win = win;
    this.doc = doc;
    this.paused = false;
    this.speaker = "idle";
    this.blocked = false;
    this.unavailable = false;
    this.needsTap = false;
    this.starting = false;
    this.needsLogin = false;
    this.ready = false;
    this.socket = null;
    this.stream = null;
    this.capture = null;
    this.node = null;
    this.resampler = null;
    this.play = null;
    this.playGain = null;
    this.nextTime = 0;
    this.sources = new Set();
    this.pendingRate = 24000;
    this.serverDone = false;
    this.retry = 0;
    this.retryTimer = null;
    this.indicator = this.#buildIndicator();
    this.render();
  }

  // ----- public -----
  start(paused = false) {
    this.paused = paused;
    // Reconnect the moment the page reports a login; the microphone itself opens only after the server says ready.
    this.doc.addEventListener("hearth:authenticated", () => {
      this.needsLogin = false;
      this.retry = 0;
      if (!this.socket) this.#connect();
      this.render();
    });
    this.#connect();
    this.render();
  }

  // Plays the real voice once. Returns false when voice is not connected, so the page can fall back.
  preview() {
    if (!this.ready || this.socket?.readyState !== 1) return false;
    this.#ensurePlayback()?.resume?.().catch?.(() => {});
    // A voice chip click saves the new voice first; give that request a moment to land.
    setTimeout(() => this.#sendJson({ type: "voice.preview" }), 350);
    return true;
  }

  handleUi(event) {
    if (event.type === "ui.mic") {
      this.paused = Boolean(event.paused);
      this.#sendJson({ type: "ui.mic", paused: this.paused });
      if (this.paused) this.#stopMic();
      else if (this.ready) this.#startMic();
    } else if (event.type === "ui.interrupt") {
      this.#stopPlayback();
      this.#sendJson({ type: "ui.interrupt" });
    }
    this.render();
  }

  // ----- indicator -----
  #buildIndicator() {
    const el = this.doc.createElement("div");
    el.id = "micIndicator";
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    Object.assign(el.style, {
      position: "fixed", top: "10px", left: "50%", transform: "translateX(-50%)", zIndex: "9999",
      font: "12px/1.2 system-ui, sans-serif", padding: "5px 11px", borderRadius: "999px",
      background: "rgba(0,0,0,.62)", color: "#f2f2f2", pointerEvents: "none", whiteSpace: "nowrap",
      border: "1px solid rgba(255,255,255,.18)",
    });
    this.doc.body.appendChild(el);
    return el;
  }

  render() {
    const trackLive = Boolean(this.stream?.getAudioTracks().some((track) => track.readyState === "live" && track.enabled));
    const state = indicatorState({
      paused: this.paused, trackLive, socketOpen: this.socket?.readyState === 1, blocked: this.blocked,
      unavailable: this.unavailable, needsTap: this.needsTap, needsLogin: this.needsLogin, speaker: this.speaker, starting: this.starting,
    });
    const live = state === "listening" || state === "waiting";
    this.indicator.textContent = (live ? "● " : "○ ") + INDICATOR_TEXT[state];
    this.indicator.dataset.state = state;
    this.indicator.style.color = live ? "#bff0c8" : "#f2f2f2";
    this.doc.documentElement.dataset.micState = state;
  }

  // ----- microphone -----
  async #startMic() {
    if (this.stream || this.unavailable) return;
    this.starting = true;
    this.render();
    const wasPaused = () => this.paused;
    try {
      const stream = await this.win.navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
      if (wasPaused()) { stream.getTracks().forEach((track) => track.stop()); return; }
      const Context = this.win.AudioContext || this.win.webkitAudioContext;
      const capture = new Context();
      await capture.audioWorklet.addModule("/shell/voice-worklet.js");
      const source = capture.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(capture, "hearth-capture");
      const mute = capture.createGain();
      mute.gain.value = 0;
      source.connect(node);
      node.connect(mute);
      mute.connect(capture.destination);
      this.resampler = new Resampler(capture.sampleRate, TARGET_RATE);
      node.port.onmessage = (message) => this.#onCaptured(message.data);
      this.stream = stream;
      this.capture = capture;
      this.node = node;
      this.blocked = false;
      this.audioBands?.attach("user", capture, source);
      stream.getAudioTracks().forEach((track) => { track.onended = () => { this.#stopMic(); this.render(); }; });
      if (capture.state === "suspended") {
        try { await capture.resume(); } catch {}
        if (capture.state === "suspended") this.#waitForGesture();
      }
    } catch (error) {
      this.#stopMic();
      this.blocked = error?.name === "NotAllowedError" || error?.name === "SecurityError" || error?.name === "NotFoundError";
    } finally {
      this.starting = false;
      this.render();
    }
  }

  #waitForGesture() {
    this.needsTap = true;
    const resume = async () => {
      this.doc.removeEventListener("pointerdown", resume, true);
      this.doc.removeEventListener("keydown", resume, true);
      try { await this.capture?.resume(); await this.#ensurePlayback()?.resume(); } catch {}
      this.needsTap = false;
      this.render();
    };
    this.doc.addEventListener("pointerdown", resume, true);
    this.doc.addEventListener("keydown", resume, true);
  }

  #stopMic() {
    this.audioBands?.detach("user");
    this.stream?.getTracks().forEach((track) => track.stop());
    try { this.node?.port && (this.node.port.onmessage = null); } catch {}
    try { this.node?.disconnect(); } catch {}
    try { this.capture?.close(); } catch {}
    this.stream = this.capture = this.node = this.resampler = null;
    this.needsTap = false;
  }

  #onCaptured(block) {
    // The page also stops sending while Hearth is thinking or speaking; the server drops it as well.
    if (this.paused || this.speaker === "think" || this.speaker === "assistant") return;
    if (this.socket?.readyState !== 1 || !this.resampler) return;
    this.socket.send(floatToInt16(this.resampler.process(block)).buffer);
  }

  // ----- socket -----
  #connect() {
    clearTimeout(this.retryTimer);
    let socket;
    try { socket = new this.win.WebSocket(voiceSocketUrl(this.win.location)); } catch { this.unavailable = true; this.render(); return; }
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    socket.onopen = () => { this.retry = 0; this.#sendJson({ type: "ui.mic", paused: this.paused }); this.render(); };
    socket.onmessage = (message) => this.#onMessage(message.data);
    socket.onclose = (event) => {
      if (this.socket === socket) this.socket = null;
      this.ready = false;
      this.#stopPlayback();
      this.#stopMic();                       // the microphone is never open without a live, authenticated socket
      if (event.code === 4503) this.unavailable = true;
      if (event.code === 4401) { this.needsLogin = true; this.render(); return; }
      if (NO_RECONNECT_CODES.has(event.code)) { this.render(); return; }
      this.retry += 1;
      this.retryTimer = setTimeout(() => this.#connect(), Math.min(15000, 500 * 2 ** this.retry));
      this.render();
    };
    socket.onerror = () => {};
  }

  #sendJson(value) {
    if (this.socket?.readyState === 1) this.socket.send(JSON.stringify(value));
  }

  #onMessage(data) {
    if (typeof data !== "string") { this.#enqueue(new Int16Array(data)); return; }
    let message;
    try { message = JSON.parse(data); } catch { return; }
    if (message.type === "voice.ready") { this.ready = true; this.needsLogin = false; if (!this.paused) this.#startMic(); this.render(); return; }
    if (message.type === "audio.sentence") { this.pendingRate = Math.min(48000, Math.max(8000, Number(message.rate) || 24000)); return; }
    if (message.type === "audio.done") { this.serverDone = true; this.#maybeEnded(); return; }
    if (!FORWARDED.has(message.type)) return;
    try {
      const event = normalizeRealtimeEvent(message);
      if (event.type === "turn.state") { this.speaker = event.speaker; if (event.speaker === "idle") this.serverDone = false; }
      if (event.type === "degraded" && event.component === "voice") this.unavailable = event.reason.includes("not installed");
      this.deliver(event);
    } catch {}
    this.render();
  }

  // ----- playback -----
  #ensurePlayback() {
    if (!this.play) {
      const Context = this.win.AudioContext || this.win.webkitAudioContext;
      this.play = new Context();
      this.playGain = this.play.createGain();
      this.playGain.connect(this.play.destination);
      this.audioBands?.attach("assistant", this.play, this.playGain);
    }
    return this.play;
  }

  #enqueue(samples) {
    const context = this.#ensurePlayback();
    if (context.state === "suspended") context.resume().catch(() => {});
    const buffer = context.createBuffer(1, samples.length, this.pendingRate);
    buffer.copyToChannel(int16ToFloat(samples), 0);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.playGain);
    const start = Math.max(context.currentTime + 0.03, this.nextTime);
    source.start(start);
    this.nextTime = start + buffer.duration;
    this.sources.add(source);
    source.onended = () => { this.sources.delete(source); this.#maybeEnded(); };
  }

  #maybeEnded() {
    if (this.serverDone && this.sources.size === 0) {
      this.serverDone = false;
      this.#sendJson({ type: "playback", state: "ended" });
    }
  }

  #stopPlayback() {
    for (const source of this.sources) { try { source.onended = null; source.stop(); } catch {} }
    this.sources.clear();
    this.nextTime = 0;
    this.serverDone = false;
  }
}
