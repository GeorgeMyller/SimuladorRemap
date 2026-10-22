/**
 * Buffer em anel por canal (RF-03; D-22): `t_sim_s` em `Float64Array`, valor em `Float32Array`.
 * Capacidade fixa (padrão 3600 = 60 s a 60 FPS); inserir além da capacidade descarta o mais antigo.
 */
export const DEFAULT_CAPACITY = 3600;

export class RingBuffer {
  readonly capacity: number;
  readonly t: Float64Array;
  readonly v: Float32Array;
  /** Índice da próxima escrita. */
  head = 0;
  size = 0;

  constructor(capacity: number = DEFAULT_CAPACITY) {
    if (!Number.isInteger(capacity) || capacity <= 0) throw new RangeError("capacidade inválida");
    this.capacity = capacity;
    this.t = new Float64Array(capacity);
    this.v = new Float32Array(capacity);
  }

  push(t: number, v: number): void {
    this.t[this.head] = t;
    this.v[this.head] = v;
    this.head = (this.head + 1) % this.capacity;
    if (this.size < this.capacity) this.size += 1;
  }

  clear(): void {
    this.head = 0;
    this.size = 0;
  }

  /** Índice físico da i-ésima amostra em ordem cronológica (0 = mais antiga). */
  private physical(i: number): number {
    const start = (this.head - this.size + this.capacity) % this.capacity;
    return (start + i) % this.capacity;
  }

  at(i: number): { t: number; v: number } | undefined {
    if (i < 0 || i >= this.size) return undefined;
    const p = this.physical(i);
    return { t: this.t[p]!, v: this.v[p]! };
  }

  latest(): { t: number; v: number } | undefined {
    return this.size === 0 ? undefined : this.at(this.size - 1);
  }

  /** Cópia ordenada de todas as amostras. */
  toArrays(): { t: Float64Array; v: Float32Array } {
    const t = new Float64Array(this.size);
    const v = new Float32Array(this.size);
    for (let i = 0; i < this.size; i += 1) {
      const p = this.physical(i);
      t[i] = this.t[p]!;
      v[i] = this.v[p]!;
    }
    return { t, v };
  }

  /** Amostras com `fromT ≤ t ≤ toT`, em ordem. */
  window(fromT: number, toT: number): { t: Float64Array; v: Float32Array } {
    let count = 0;
    for (let i = 0; i < this.size; i += 1) {
      const ti = this.t[this.physical(i)]!;
      if (ti >= fromT && ti <= toT) count += 1;
    }
    const t = new Float64Array(count);
    const v = new Float32Array(count);
    let k = 0;
    for (let i = 0; i < this.size; i += 1) {
      const p = this.physical(i);
      const ti = this.t[p]!;
      if (ti >= fromT && ti <= toT) {
        t[k] = ti;
        v[k] = this.v[p]!;
        k += 1;
      }
    }
    return { t, v };
  }

  /** Valor da amostra mais próxima de `t` (para o cursor), ou `undefined`. */
  valueAt(t: number): number | undefined {
    if (this.size === 0) return undefined;
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < this.size; i += 1) {
      const d = Math.abs(this.t[this.physical(i)]! - t);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    }
    return this.at(best)?.v;
  }
}
