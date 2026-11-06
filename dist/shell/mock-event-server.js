export class MockEventServer {
  constructor({ clock = () => performance.now() / 1000, schedule = (callback) => queueMicrotask(callback) } = {}) {
    this.clock = clock;
    this.schedule = schedule;
    this.client = null;
    this.received = [];
  }

  connect(client) { this.client = client; }
  disconnect(client) { if (this.client === client) this.client = null; }

  send(event) {
    this.received.push(Object.freeze({ ...event }));
    if (event.type === "ui.mic") {
      this.schedule(() => this.emit({ type: "ui.mic.ack", paused: event.paused }));
    }
  }

  emit(event) {
    if (!this.client) return null;
    const envelope = { ...event, v: 1, ts: Number.isFinite(event.ts) ? event.ts : this.clock() };
    return this.client.receive(envelope);
  }

  replay(events, intervalMs = 0) {
    let index = 0;
    const next = () => {
      if (index >= events.length) return;
      this.emit(events[index++]);
      if (index < events.length) setTimeout(next, intervalMs);
    };
    next();
  }
}
