/**
 * `AudioContext` falso completo para testes do grafo de áudio (003 T007): regista todos os nós,
 * as ligações e as automações de cada parâmetro. Inclui WaveShaper, Convolver, Delay e
 * `playbackRate`, ausentes no mock partilhado da cockpit.
 */
export interface ParamEvent {
  kind: "set" | "target" | "linear" | "exponential" | "cancel";
  value: number;
  time: number;
}

export class GraphParam {
  value: number;
  readonly events: ParamEvent[] = [];

  constructor(value = 0) {
    this.value = value;
  }

  private push(kind: ParamEvent["kind"], value: number, time: number): this {
    this.events.push({ kind, value, time });
    if (kind !== "cancel") this.value = value;
    return this;
  }

  setValueAtTime(v: number, t: number) {
    return this.push("set", v, t);
  }
  setTargetAtTime(v: number, t: number) {
    return this.push("target", v, t);
  }
  linearRampToValueAtTime(v: number, t: number) {
    return this.push("linear", v, t);
  }
  exponentialRampToValueAtTime(v: number, t: number) {
    return this.push("exponential", v, t);
  }
  cancelScheduledValues(t: number) {
    return this.push("cancel", 0, t);
  }
}

export type NodeKind =
  | "destination"
  | "gain"
  | "biquad"
  | "oscillator"
  | "bufferSource"
  | "waveShaper"
  | "convolver"
  | "delay"
  | "compressor";

export class GraphNode {
  readonly outputs: GraphNode[] = [];
  started: number | null = null;
  stopped: number | null = null;
  [key: string]: unknown;

  constructor(readonly kind: NodeKind) {}

  connect(n: GraphNode) {
    this.outputs.push(n);
    return n;
  }
  disconnect() {
    this.outputs.length = 0;
  }
  start(when = 0) {
    this.started = when;
  }
  stop(when = 0) {
    this.stopped = when;
  }
}

export class GraphAudioContext {
  static instances: GraphAudioContext[] = [];
  state: AudioContextState = "suspended";
  currentTime = 0;
  readonly sampleRate = 48_000;
  readonly nodes: GraphNode[] = [];
  readonly destination = new GraphNode("destination");

  constructor() {
    GraphAudioContext.instances.push(this);
  }

  resume() {
    this.state = "running";
    return Promise.resolve();
  }
  suspend() {
    this.state = "suspended";
    return Promise.resolve();
  }
  close() {
    this.state = "closed";
    return Promise.resolve();
  }

  private add(kind: NodeKind, props: Record<string, unknown>): GraphNode {
    const node = Object.assign(new GraphNode(kind), props);
    this.nodes.push(node);
    return node;
  }

  createGain() {
    return this.add("gain", { gain: new GraphParam(1) });
  }
  createBiquadFilter() {
    return this.add("biquad", { type: "lowpass", frequency: new GraphParam(350), Q: new GraphParam(1), gain: new GraphParam(0) });
  }
  createOscillator() {
    return this.add("oscillator", { type: "sine", frequency: new GraphParam(440), detune: new GraphParam(0) });
  }
  createBufferSource() {
    return this.add("bufferSource", { buffer: null, loop: false, playbackRate: new GraphParam(1) });
  }
  createWaveShaper() {
    return this.add("waveShaper", { curve: null, oversample: "none" });
  }
  createConvolver() {
    return this.add("convolver", { buffer: null, normalize: true });
  }
  createDelay() {
    return this.add("delay", { delayTime: new GraphParam(0) });
  }
  createDynamicsCompressor() {
    return this.add("compressor", { threshold: new GraphParam(-24), knee: new GraphParam(30), ratio: new GraphParam(12), attack: new GraphParam(0.003), release: new GraphParam(0.25) });
  }
  createBuffer(_channels: number, length: number, sampleRate: number) {
    const data = new Float32Array(length);
    return { length, sampleRate, duration: length / sampleRate, numberOfChannels: 1, getChannelData: () => data };
  }

  ofKind(kind: NodeKind): GraphNode[] {
    return this.nodes.filter((n) => n.kind === kind);
  }
}

export const graphAudioFactory = () => new GraphAudioContext() as unknown as AudioContext;

/** Nó falso por trás de um nó público (ex.: `engine.graph.master`). */
export function asNode(node: unknown): GraphNode {
  return node as GraphNode;
}

export function paramOf(node: GraphNode, key: string): GraphParam {
  return node[key] as GraphParam;
}

/** Todos os nós alcançáveis a jusante de `from` (busca em largura). */
export function downstream(from: GraphNode): Set<GraphNode> {
  const seen = new Set<GraphNode>();
  const queue = [...from.outputs];
  while (queue.length > 0) {
    const n = queue.shift()!;
    if (seen.has(n)) continue;
    seen.add(n);
    queue.push(...n.outputs);
  }
  return seen;
}

/** Caminho seguindo sempre a 1.ª saída a partir de `from` até `to` (inclusive), ou `null`. */
export function firstPath(from: GraphNode, to: GraphNode, limit = 32): GraphNode[] | null {
  const path = [from];
  let cur = from;
  while (cur !== to && path.length < limit) {
    const next = cur.outputs[0];
    if (!next) return null;
    path.push(next);
    cur = next;
  }
  return cur === to ? path : null;
}

/** Nó descrito para asserções legíveis: `biquad:lowpass`, `waveShaper`, `gain`. */
export function describeNode(n: GraphNode): string {
  return n.kind === "biquad" || n.kind === "oscillator" ? `${n.kind}:${String(n.type)}` : n.kind;
}
