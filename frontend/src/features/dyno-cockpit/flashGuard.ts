/**
 * Limitador de flashes (WCAG 2.3.1; RF-21, RNF-06): no máximo `maxHz` transições de
 * luminância forte por segundo. Banners, explosão e chama consultam-no antes de piscar.
 */
export class FlashLimiter {
  private readonly minIntervalMs: number;
  private last = -Infinity;

  constructor(maxHz = 3) {
    this.minIntervalMs = 1000 / maxHz;
  }

  /** `true` se um flash pode acontecer em `nowMs`; regista-o. */
  tryFlash(nowMs: number): boolean {
    if (nowMs - this.last < this.minIntervalMs) return false;
    this.last = nowMs;
    return true;
  }
}

/** PRNG determinístico (mulberry32) semeado por inteiro (ex.: `seq`). */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
