const SPEAKERS = new Set(["idle", "user", "think", "assistant"]);
const MEMORY_STATUSES = new Set(["candidate", "confirmed", "reinforced", "corrected", "retired"]);
const MELT_STATES = new Set(["none", "scheduled"]);

function finite(value, fallback = 0) { return Number.isFinite(value) ? value : fallback; }
function clamp(value, low, high) { return Math.min(high, Math.max(low, finite(value, low))); }
function text(value, limit = 4096) { return String(value ?? "").slice(0, limit); }

export function normalizeRealtimeEvent(value) {
  const input = typeof value === "string" ? JSON.parse(value) : value;
  if (!input || typeof input !== "object" || input.v !== 1 || !Number.isFinite(input.ts)) throw new TypeError("invalid realtime envelope");
  const base = { type: text(input.type, 64), v: 1, ts: input.ts };
  switch (base.type) {
    case "turn.state":
      if (!SPEAKERS.has(input.speaker)) throw new TypeError("invalid speaker");
      return { ...base, speaker: input.speaker, turn_id: text(input.turn_id, 128) };
    case "transcript.partial":
      if (input.role !== "user" && input.role !== "assistant") throw new TypeError("invalid transcript role");
      return { ...base, turn_id: text(input.turn_id, 128), role: input.role, text: text(input.text) };
    case "assistant.delivered":
      return { ...base, turn_id: text(input.turn_id, 128), text_so_far: text(input.text_so_far), final: Boolean(input.final) };
    case "memory.candidate":
      if (input.status !== "candidate") throw new TypeError("candidate event must be candidate");
      return { ...base, id: text(input.id, 128), category: text(input.category, 64), text: text(input.text), status: "candidate" };
    case "memory.updated":
      if (!MEMORY_STATUSES.has(input.status)) throw new TypeError("invalid memory status");
      return { ...base, id: text(input.id, 128), status: input.status, text: text(input.text) };
    case "memory.removed":
      return { ...base, id: text(input.id, 128) };
    case "calm.estimate":
      return { ...base, value: clamp(input.value, 0, 1) };
    case "melt.state":
      if (!MELT_STATES.has(input.state)) throw new TypeError("invalid melt state");
      return { ...base, state: input.state, due_at: input.state === "scheduled" ? Math.max(0, finite(input.due_at)) : null };
    case "settings.changed":
      if (!Array.isArray(input.keys)) throw new TypeError("invalid settings keys");
      return { ...base, keys: input.keys.map((key) => text(key, 128)).slice(0, 64) };
    case "degraded":
      return { ...base, component: text(input.component, 128), reason: text(input.reason, 512) };
    case "ui.mic.ack":
      return { ...base, paused: Boolean(input.paused) };
    default:
      throw new TypeError("unknown realtime event");
  }
}

export class RealtimeClient {
  constructor({ onEvent = () => {}, clock = () => performance.now() / 1000 } = {}) {
    this.onEvent = onEvent;
    this.clock = clock;
    this.transport = null;
    this.lastBackendTs = -Infinity;
  }

  connect(transport) {
    this.transport = transport;
    transport.connect?.(this);
    return this;
  }

  receive(raw) {
    const event = normalizeRealtimeEvent(raw);
    if (event.ts < this.lastBackendTs) throw new RangeError("out-of-order realtime event");
    this.lastBackendTs = event.ts;
    this.onEvent(event);
    return event;
  }

  send(message) {
    const type = text(message?.type, 64);
    if (type !== "ui.mic" && type !== "ui.interrupt") throw new TypeError("unsupported browser event");
    const event = { type, v: 1, ts: finite(this.clock()) };
    if (type === "ui.mic") event.paused = Boolean(message.paused);
    else event.turn_id = text(message.turn_id, 128);
    this.transport?.send?.(event);
    return event;
  }

  dispose() {
    this.transport?.disconnect?.(this);
    this.transport = null;
    this.onEvent = () => {};
  }
}
