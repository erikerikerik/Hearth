import { RealtimeClient } from "./realtime.js";
import { MockEventServer } from "./mock-event-server.js";
import { VoiceLoop } from "./voice.js";

// The mock transport only acknowledges mic pause. Its injection hooks
// (receive, replay, mockServer) exist for synthetic acceptance and are exposed
// only when the server reports dev_tools=true. Production exposes send() only.
const mockServer = new MockEventServer();
const client = new RealtimeClient({
  onEvent(event) { window.__hearth?.receiveRealtimeEvent?.(event); },
}).connect(mockServer);

let devTools = false;
try {
  const response = await fetch("/healthz", { cache: "no-store", credentials: "same-origin" });
  devTools = response.ok && (await response.json()).dev_tools === true;
} catch { devTools = false; }

// Hands-free voice. On by default; in dev-tools mode (the synthetic acceptance suite) it is off
// unless the page is opened with ?voice=1. The loop reports "voice not installed" on its own if needed.
let voice = null;
const wantsVoice = devTools ? new URLSearchParams(location.search).get("voice") === "1" : true;
if (wantsVoice && navigator.mediaDevices?.getUserMedia) {
  // audio-bootstrap.js may load after this module, so the band hooks are looked up at call time.
  const audioBands = {
    attach: (...args) => window.hearthAudioBands?.attach(...args),
    detach: (...args) => window.hearthAudioBands?.detach(...args),
  };
  voice = new VoiceLoop({
    deliver(event) { window.__hearth?.receiveRealtimeEvent?.(event); },
    audioBands,
  });
}

const surface = {
  send(message) {
    const event = client.send(message);
    voice?.handleUi(event);
    return event;
  },
};
if (devTools) {
  surface.receive = (message) => client.receive(message);
  surface.replay = (events, intervalMs) => mockServer.replay(events, intervalMs);
  surface.mockServer = mockServer;
}
window.hearthRealtime = Object.freeze(surface);
window.hearthVoicePreview = () => (voice ? voice.preview() : false);

document.dispatchEvent(new CustomEvent("hearth:realtime-ready"));
document.documentElement.dataset.realtimeTransport = devTools ? "mock-v1-dev" : "mock-v1";
const initiallyPaused = Boolean(window.__hearth?.S?.paused);
client.send({ type: "ui.mic", paused: initiallyPaused });
voice?.start(initiallyPaused);
