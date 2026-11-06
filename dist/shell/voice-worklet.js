// Runs on the audio thread. Collects 128-sample blocks into ~43 ms chunks and posts them to the page.
class HearthCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(2048);
    this.fill = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) {
      for (let index = 0; index < channel.length; index += 1) {
        this.buffer[this.fill] = channel[index];
        this.fill += 1;
        if (this.fill === this.buffer.length) {
          this.port.postMessage(this.buffer.slice(0));
          this.fill = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("hearth-capture", HearthCapture);
