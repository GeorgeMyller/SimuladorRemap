/**
 * Construção do grafo Web Audio com detecção de capacidades (003 D-05). Navegadores antigos e mocks
 * de teste podem não ter `WaveShaperNode`, `ConvolverNode`, `DelayNode` ou alguns `AudioParam`;
 * nesses casos o nó vira um ganho unitário ou o parâmetro é ignorado, sem lançar exceções.
 */
export type Ctx = AudioContext;

type Maybe<T> = { [K in keyof T]?: T[K] };

/** Parâmetro opcional (ex.: `playbackRate` ou `gain` de biquad ausente num mock). */
export function paramOf<T extends object, K extends keyof T>(node: T, key: K): T[K] | undefined {
  return (node as Maybe<T>)[key];
}

/** Rampa exponencial suave (sem zipper noise). */
export function smooth(param: AudioParam | undefined, value: number, t: number, tau: number): void {
  param?.setTargetAtTime(value, t, tau);
}

/** Cancela automações futuras quando o contexto suporta. */
export function cancelFrom(param: AudioParam | undefined, t: number): void {
  const cancel = param ? (param as Maybe<AudioParam>).cancelScheduledValues : undefined;
  if (param && cancel) cancel.call(param, t);
}

export function gainNode(ctx: Ctx, value: number): GainNode {
  const g = ctx.createGain();
  g.gain.value = value;
  return g;
}

export function filterNode(ctx: Ctx, type: BiquadFilterType, hz: number, q: number, gainDb = 0): BiquadFilterNode {
  const f = ctx.createBiquadFilter();
  f.type = type;
  f.frequency.value = hz;
  const qParam = paramOf(f, "Q");
  if (qParam) qParam.value = q;
  const gParam = paramOf(f, "gain");
  if (gParam) gParam.value = gainDb;
  return f;
}

/** `WaveShaperNode` com sobreamostragem 4×; sem suporte, um ganho unitário. */
export function shaperNode(ctx: Ctx, curve: Float32Array): AudioNode {
  const create = (ctx as Maybe<Ctx>).createWaveShaper;
  if (!create) return gainNode(ctx, 1);
  const shaper = create.call(ctx);
  shaper.curve = curve as Float32Array<ArrayBuffer>;
  shaper.oversample = "4x";
  return shaper;
}

export function bufferFrom(ctx: Ctx, data: Float32Array): AudioBuffer {
  const buffer = ctx.createBuffer(1, data.length, ctx.sampleRate);
  buffer.getChannelData(0).set(data);
  return buffer;
}

/** Fonte em laço iniciada imediatamente (com deslocamento para descorrelacionar vozes de ruído). */
export function loopSource(ctx: Ctx, buffer: AudioBuffer, offsetS = 0): AudioBufferSourceNode {
  const src = ctx.createBufferSource();
  src.buffer = buffer;
  src.loop = true;
  src.start(0, offsetS);
  return src;
}

export function chain(...nodes: AudioNode[]): void {
  for (let i = 1; i < nodes.length; i += 1) nodes[i - 1]!.connect(nodes[i]!);
}

/**
 * Reverb curto dos pops: `ConvolverNode` com resposta impulsiva sintética; sem suporte, eco de
 * realimentação baixa (`DelayNode`); sem nenhum dos dois, `null`.
 */
export function shortReverb(ctx: Ctx, impulse: Float32Array): { input: AudioNode; output: AudioNode } | null {
  const createConvolver = (ctx as Maybe<Ctx>).createConvolver;
  if (createConvolver) {
    const conv = createConvolver.call(ctx);
    conv.normalize = true;
    conv.buffer = bufferFrom(ctx, impulse);
    return { input: conv, output: conv };
  }
  const createDelay = (ctx as Maybe<Ctx>).createDelay;
  if (!createDelay) return null;
  const delay = createDelay.call(ctx, 0.2);
  delay.delayTime.value = 0.045;
  const damp = filterNode(ctx, "lowpass", 2500, 0);
  const feedback = gainNode(ctx, 0.22);
  chain(delay, damp, feedback, delay);
  return { input: delay, output: damp };
}

/** Para fontes em laço, ignorando as que já pararam. */
export function stopAll(nodes: readonly AudioScheduledSourceNode[]): void {
  for (const n of nodes) {
    try {
      n.stop();
    } catch {
      /* já parado */
    }
  }
}
