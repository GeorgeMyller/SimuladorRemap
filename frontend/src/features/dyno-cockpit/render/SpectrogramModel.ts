/**
 * Matriz tempo × frequência do espectrograma de knock (RF-09): janela de 10 s a 50 colunas/s,
 * 256 bins de 0–20 kHz (largura 78,125 Hz). Colunas num anel; cada célula guarda dB.
 */
export const SPECTRUM_BINS = 256;
export const SPECTRUM_MAX_HZ = 20_000;
export const BIN_WIDTH_HZ = SPECTRUM_MAX_HZ / SPECTRUM_BINS;
export const DB_MIN = -80;
export const DB_MAX = 0;

export class SpectrogramModel {
  readonly columns: number;
  readonly bins: number;
  readonly data: Float32Array;
  head = 0;
  filled = 0;
  binsHz: Float32Array;
  resonanceHz: number[] = [];
  /** Decimação (EC-12): aceita 1 coluna a cada `stride` empurradas. */
  stride = 1;
  private skip = 0;

  constructor(columns = 500, bins = SPECTRUM_BINS) {
    this.columns = columns;
    this.bins = bins;
    this.data = new Float32Array(columns * bins).fill(DB_MIN);
    this.binsHz = Float32Array.from({ length: bins }, (_, i) => i * BIN_WIDTH_HZ);
  }

  /** Empurra uma coluna; devolve `true` se foi gravada (respeita a decimação). */
  push(magnitudeDb: ArrayLike<number>, binsHz?: ArrayLike<number>, resonanceHz?: readonly number[]): boolean {
    if (binsHz && binsHz.length === this.bins) this.binsHz = Float32Array.from(binsHz);
    if (resonanceHz) this.resonanceHz = [...resonanceHz];
    this.skip = (this.skip + 1) % this.stride;
    if (this.skip !== 0 && this.stride > 1) return false;
    const base = this.head * this.bins;
    for (let i = 0; i < this.bins; i += 1) {
      const v = magnitudeDb[i];
      this.data[base + i] = typeof v === "number" && Number.isFinite(v) ? v : DB_MIN;
    }
    this.head = (this.head + 1) % this.columns;
    this.filled = Math.min(this.columns, this.filled + 1);
    return true;
  }

  /** Índice físico da coluna mais recente. */
  latestColumn(): number {
    return (this.head - 1 + this.columns) % this.columns;
  }

  column(physical: number): Float32Array {
    return this.data.subarray(physical * this.bins, (physical + 1) * this.bins);
  }

  /** Linha (bin) de maior intensidade na coluna mais recente. */
  peakBin(): number {
    if (this.filled === 0) return -1;
    const col = this.column(this.latestColumn());
    let best = 0;
    for (let i = 1; i < col.length; i += 1) if (col[i]! > col[best]!) best = i;
    return best;
  }

  peakFrequencyHz(): number | null {
    const bin = this.peakBin();
    return bin < 0 ? null : this.binsHz[bin]!;
  }

  /** Normaliza dB em 0..1 para o mapa de cores. */
  static normalize(db: number): number {
    return Math.min(1, Math.max(0, (db - DB_MIN) / (DB_MAX - DB_MIN)));
  }

  /** Coluna mais recente em bytes 0..255 (textura WebGL / ImageData). */
  latestColumnBytes(): Uint8Array {
    const col = this.column(this.latestColumn());
    const out = new Uint8Array(this.bins);
    for (let i = 0; i < this.bins; i += 1) out[i] = Math.round(SpectrogramModel.normalize(col[i]!) * 255);
    return out;
  }

  clear(): void {
    this.data.fill(DB_MIN);
    this.head = 0;
    this.filled = 0;
  }
}

/** Mapa de cores "inferno" simplificado (5 paradas), 0..1 → RGB. */
export function heatColor(x: number): [number, number, number] {
  const stops: [number, number, number][] = [
    [0, 0, 4],
    [87, 16, 110],
    [188, 55, 84],
    [249, 142, 9],
    [252, 255, 164],
  ];
  const t = Math.min(1, Math.max(0, x)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(t));
  const f = t - i;
  const a = stops[i]!;
  const b = stops[i + 1]!;
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
  ];
}
