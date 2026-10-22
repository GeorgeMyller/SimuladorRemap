/**
 * Pilha de desfazer/refazer por calibração aberta (tuning RF-09, EC-08; data-model 4.3).
 * Guarda deltas de células (não cópias de tabelas, RNF-04). Capacidade padrão 100, mínimo 50;
 * acima da capacidade descarta o passo mais antigo (FIFO). `push` limpa o `future`.
 */
import type { TableDelta } from "../model";

export const DEFAULT_UNDO_CAPACITY = 100;
export const MIN_UNDO_CAPACITY = 50;

export class UndoStack {
  readonly capacity: number;
  past: TableDelta[] = [];
  future: TableDelta[] = [];

  constructor(capacity = DEFAULT_UNDO_CAPACITY) {
    this.capacity = Math.max(MIN_UNDO_CAPACITY, Math.floor(capacity));
  }

  push(delta: TableDelta): void {
    if (delta.cells.length === 0) return;
    this.past.push(delta);
    if (this.past.length > this.capacity) this.past.splice(0, this.past.length - this.capacity);
    this.future = [];
  }

  undo(): TableDelta | undefined {
    const d = this.past.pop();
    if (d) this.future.push(d);
    return d;
  }

  redo(): TableDelta | undefined {
    const d = this.future.pop();
    if (d) this.past.push(d);
    return d;
  }

  get canUndo(): boolean {
    return this.past.length > 0;
  }

  get canRedo(): boolean {
    return this.future.length > 0;
  }

  clear(): void {
    this.past = [];
    this.future = [];
  }
}
