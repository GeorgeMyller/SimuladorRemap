/**
 * Mock de Web Audio para o vitest (cockpit RF-18, RF-19; D-23).
 * O `AudioContext` nasce `suspended` (política de autoplay: mudo até ao 1.º gesto) e
 * passa a `running` em `resume()`. Instâncias criadas ficam em `MockAudioContext.instances`.
 */

export class MockAudioParam {
  value: number;
  readonly events: { type: string; value: number; time: number }[] = [];

  constructor(value = 0) {
    this.value = value;
  }

  private push(type: string, value: number, time: number): this {
    this.events.push({ type, value, time });
    this.value = value;
    return this;
  }

  setValueAtTime(value: number, time: number): this {
    return this.push("set", value, time);
  }

  linearRampToValueAtTime(value: number, time: number): this {
    return this.push("linear", value, time);
  }

  exponentialRampToValueAtTime(value: number, time: number): this {
    return this.push("exponential", value, time);
  }

  setTargetAtTime(value: number, time: number, _constant: number): this {
    return this.push("target", value, time);
  }

  cancelScheduledValues(_time: number): this {
    return this;
  }
}

export class MockAudioNode {
  readonly connections: unknown[] = [];
  readonly context: MockAudioContext;

  constructor(context: MockAudioContext) {
    this.context = context;
  }

  connect<T>(destination: T): T {
    this.connections.push(destination);
    return destination;
  }

  disconnect(): void {
    this.connections.length = 0;
  }
}

export class MockScheduledNode extends MockAudioNode {
  started: number | null = null;
  stopped: number | null = null;
  onended: (() => void) | null = null;

  start(when = 0): void {
    this.started = when;
  }

  stop(when = 0): void {
    this.stopped = when;
    this.onended?.();
  }
}

export class MockOscillatorNode extends MockScheduledNode {
  type: OscillatorType = "sine";
  readonly frequency = new MockAudioParam(440);
  readonly detune = new MockAudioParam(0);
}

export class MockGainNode extends MockAudioNode {
  readonly gain = new MockAudioParam(1);
}

export class MockBiquadFilterNode extends MockAudioNode {
  type: BiquadFilterType = "lowpass";
  readonly frequency = new MockAudioParam(350);
  readonly Q = new MockAudioParam(1);
  readonly gain = new MockAudioParam(0);
}

export class MockBufferSourceNode extends MockScheduledNode {
  buffer: unknown = null;
  loop = false;
  readonly playbackRate = new MockAudioParam(1);
}

export class MockAudioContext {
  static instances: MockAudioContext[] = [];
  state: AudioContextState = "suspended";
  currentTime = 0;
  readonly sampleRate = 48_000;
  readonly destination: MockAudioNode;
  onstatechange: (() => void) | null = null;

  constructor() {
    this.destination = new MockAudioNode(this);
    MockAudioContext.instances.push(this);
  }

  private setState(state: AudioContextState): Promise<void> {
    this.state = state;
    this.onstatechange?.();
    return Promise.resolve();
  }

  resume(): Promise<void> {
    return this.setState("running");
  }

  suspend(): Promise<void> {
    return this.setState("suspended");
  }

  close(): Promise<void> {
    return this.setState("closed");
  }

  /** Avança o relógio de áudio (só testes). */
  advance(seconds: number): void {
    this.currentTime += seconds;
  }

  createOscillator(): MockOscillatorNode {
    return new MockOscillatorNode(this);
  }

  createGain(): MockGainNode {
    return new MockGainNode(this);
  }

  createBiquadFilter(): MockBiquadFilterNode {
    return new MockBiquadFilterNode(this);
  }

  createBufferSource(): MockBufferSourceNode {
    return new MockBufferSourceNode(this);
  }

  createBuffer(channels: number, length: number, sampleRate: number) {
    const data = Array.from({ length: channels }, () => new Float32Array(length));
    return {
      numberOfChannels: channels,
      length,
      sampleRate,
      duration: length / sampleRate,
      getChannelData: (channel: number) => data[channel] ?? new Float32Array(0),
    };
  }

  createDynamicsCompressor(): MockAudioNode {
    return new MockAudioNode(this);
  }

  createStereoPanner(): MockAudioNode & { pan: MockAudioParam } {
    return Object.assign(new MockAudioNode(this), { pan: new MockAudioParam(0) });
  }

  createWaveShaper(): MockAudioNode & { curve: Float32Array | null } {
    return Object.assign(new MockAudioNode(this), { curve: null });
  }
}

export function installAudioMock(): void {
  Object.defineProperty(globalThis, "AudioContext", {
    configurable: true,
    writable: true,
    value: MockAudioContext,
  });
  Object.defineProperty(globalThis, "webkitAudioContext", {
    configurable: true,
    writable: true,
    value: MockAudioContext,
  });
}

export function resetAudioMocks(): void {
  MockAudioContext.instances = [];
}
