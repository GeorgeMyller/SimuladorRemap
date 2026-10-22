/**
 * Estado da animação do carro no rolo (RF-11, RF-21): rodas giram pela velocidade do rolo, a
 * carroçaria vibra com amplitude proporcional ao RPM, chamas e fagulhas no escape por
 * `overrun_afterfire`, e fumaça/detritos/fagulhas próprios de cada modo de falha. Partículas com
 * teto de 300 (100 em degradação, EC-12); todo o aleatório é semeado (determinístico).
 */
import { FlashLimiter, mulberry32 } from "../flashGuard";

import { DEFAULT_FAILURE_FX, failureFxFor, type EmitPoint, type FailureFx, type ParticleTone } from "./failureFx";

export type { ParticleTone } from "./failureFx";

export const WHEEL_RADIUS_M = 0.31;
export const ROLLER_RADIUS_M = 0.6096;
export const MAX_PARTICLES = 300;
export const DEGRADED_PARTICLES = 100;
/** Tempo até as rodas pararem após a falha (≤ 2 s). */
export const STOP_AFTER_FAILURE_S = 1.5;
/** Teto de partículas por rajada de pops & bangs. */
export const MAX_AFTERFIRE_PARTICLES = 18;
/** Brilho térmico residual enquanto o motor fumega. */
const HEAT_FLOOR = 0.35;

export type ParticleKind = "flame" | "spark" | "smoke" | "debris";

export interface Particle {
  kind: ParticleKind;
  tone: ParticleTone;
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
  size: number;
}

export interface CarInputs {
  rollerSpeedKmh: number;
  rpm: number;
  maxRpm: number;
  throttlePct: number;
  /** Novos estalos desde o último passo. */
  afterfire: number;
  afterfireSeq: number;
}

type Point = { x: number; y: number };

export class CarAnimator {
  wheelAngle = 0;
  rollerAngle = 0;
  /** Fator de rotação (1 = segue o rolo; decai a 0 após a falha). */
  spinFactor = 1;
  vibrationAmp = 0;
  vibrationOffset = 0;
  smoking = false;
  smokeStartedAtS: number | null = null;
  exploded = false;
  explosionFlash = 0;
  /** Clarão local da chama no escape (pops & bangs), 0..1. */
  exhaustFlash = 0;
  /** Brilho térmico do coletor/turbina após a falha (0..1). */
  heatGlow = 0;
  /** Modo da falha atual (`event.failure.mode`), se conhecido. */
  failureMode: string | null = null;
  t = 0;
  particles: Particle[] = [];
  maxParticles = MAX_PARTICLES;
  /** Posições no referencial do canvas (definidas pela vista). */
  exhaust: Point = { x: 60, y: 150 };
  engineBay: Point = { x: 300, y: 120 };
  turbo: Point = { x: 262, y: 128 };
  private fx: FailureFx = DEFAULT_FAILURE_FX;
  private readonly flash = new FlashLimiter(3);

  configure(opts: { exhaust?: Point; engineBay?: Point; turbo?: Point; maxParticles?: number }): void {
    if (opts.exhaust) this.exhaust = opts.exhaust;
    if (opts.engineBay) this.engineBay = opts.engineBay;
    if (opts.turbo) this.turbo = opts.turbo;
    if (opts.maxParticles !== undefined) {
      this.maxParticles = opts.maxParticles;
      if (this.particles.length > this.maxParticles) this.particles.splice(0, this.particles.length - this.maxParticles);
    }
  }

  /** Amplitude de vibração (px) proporcional ao RPM. */
  static vibrationFor(rpm: number, maxRpm: number): number {
    const r = Math.max(0, rpm) / Math.max(1000, maxRpm);
    return 0.3 + 2.7 * Math.min(1.2, r);
  }

  /** Velocidade angular das rodas (rad/s) a partir do rolo (v = ω·r). */
  static wheelOmega(rollerSpeedKmh: number): number {
    return Math.max(0, rollerSpeedKmh) / 3.6 / WHEEL_RADIUS_M;
  }

  static rollerOmega(rollerSpeedKmh: number): number {
    return Math.max(0, rollerSpeedKmh) / 3.6 / ROLLER_RADIUS_M;
  }

  private pointOf(at: EmitPoint): Point {
    if (at === "exhaust") return this.exhaust;
    if (at === "turbo") return this.turbo;
    return this.engineBay;
  }

  /** Falha catastrófica: fumaça imediata, explosão (1 flash), rodas param em ≤ 2 s; efeitos pelo modo. */
  triggerFailure(seed: number, mode: string | null = null): void {
    if (this.exploded) return;
    this.exploded = true;
    this.smoking = true;
    this.smokeStartedAtS = this.t;
    this.failureMode = mode;
    this.fx = failureFxFor(mode);
    this.heatGlow = this.fx.heat;
    if (this.flash.tryFlash(this.t * 1000)) this.explosionFlash = 1;
    const rnd = mulberry32(seed);
    const fx = this.fx;
    for (let i = 0; i < fx.debris; i += 1) {
      const a = rnd() * Math.PI * 2;
      const s = 60 + rnd() * 160;
      this.emit("debris", fx.debrisTone, this.engineBay, Math.cos(a) * s, Math.sin(a) * s - 60, 0.8 + rnd() * 0.6, 2 + rnd() * 3);
    }
    const sparkFrom = this.pointOf(fx.sparkAt);
    for (let i = 0; i < fx.sparks; i += 1) {
      const a = -Math.PI * (0.1 + 0.8 * rnd());
      const s = 140 + rnd() * 220;
      this.emit("spark", fx.sparkTone, sparkFrom, Math.cos(a) * s, Math.sin(a) * s, 0.25 + rnd() * 0.45, 1.2 + rnd() * 1.6);
    }
  }

  /** Restaura o motor: limpa fumaça e volta a seguir o rolo. */
  reset(): void {
    this.exploded = false;
    this.smoking = false;
    this.smokeStartedAtS = null;
    this.spinFactor = 1;
    this.explosionFlash = 0;
    this.exhaustFlash = 0;
    this.heatGlow = 0;
    this.failureMode = null;
    this.fx = DEFAULT_FAILURE_FX;
    this.particles = [];
  }

  step(dtS: number, input: CarInputs): void {
    const dt = Math.min(0.1, Math.max(0, dtS));
    this.t += dt;
    if (this.exploded && this.smokeStartedAtS !== null) {
      const since = this.t - this.smokeStartedAtS;
      this.spinFactor = Math.max(0, 1 - since / STOP_AFTER_FAILURE_S);
    }
    const omega = CarAnimator.wheelOmega(input.rollerSpeedKmh) * this.spinFactor;
    this.wheelAngle = (this.wheelAngle + omega * dt) % (Math.PI * 2);
    this.rollerAngle = (this.rollerAngle - CarAnimator.rollerOmega(input.rollerSpeedKmh) * this.spinFactor * dt) % (Math.PI * 2);
    const rpm = this.exploded ? input.rpm * this.spinFactor : input.rpm;
    this.vibrationAmp = CarAnimator.vibrationFor(rpm, input.maxRpm);
    // Vibração determinística: soma de senos na frequência de rotação (sem aleatório).
    const f = Math.max(5, rpm / 60);
    this.vibrationOffset = this.vibrationAmp * Math.sin(this.t * f * 2 * Math.PI * 0.05) * Math.cos(this.t * 23);
    this.explosionFlash = Math.max(0, this.explosionFlash - dt * 2.5);
    this.exhaustFlash = Math.max(0, this.exhaustFlash - dt * 9);
    if (this.heatGlow > HEAT_FLOOR) this.heatGlow = Math.max(HEAT_FLOOR, this.heatGlow - dt * 0.4);

    if (input.afterfire > 0 && !this.exploded) this.emitAfterfire(input.afterfire, input.afterfireSeq);
    if (this.smoking) this.emitSmoke();
    this.advance(dt);
  }

  /** Pops & bangs: labareda longa no escape (núcleo amarelo + chama laranja + fagulhas). */
  private emitAfterfire(count: number, seq: number): void {
    const rnd = mulberry32(seq);
    const n = Math.min(MAX_AFTERFIRE_PARTICLES, count * 4);
    this.exhaustFlash = 1;
    for (let i = 0; i < n; i += 1) {
      const tone: ParticleTone = i % 4 === 0 ? "spark" : i % 4 === 1 ? "flameCore" : "flame";
      const kind: ParticleKind = tone === "spark" ? "spark" : "flame";
      const speed = 150 + rnd() * 180;
      this.emit(kind, tone, this.exhaust, -speed, (rnd() - 0.5) * 60, 0.18 + rnd() * 0.24, tone === "spark" ? 1.5 + rnd() * 1.5 : 5 + rnd() * 6);
    }
  }

  private emitSmoke(): void {
    const fx = this.fx;
    const from = this.pointOf(fx.smokeAt);
    const rnd = mulberry32(Math.floor(this.t * 1000));
    const fromExhaust = fx.smokeAt === "exhaust";
    for (let i = 0; i < fx.smokePerStep; i += 1) {
      const vx = fromExhaust ? -(30 + rnd() * 40) : (rnd() - 0.5) * 20;
      const p = { x: from.x + (rnd() - 0.5) * (fromExhaust ? 8 : 40), y: from.y };
      this.emit("smoke", fx.smokeTone, p, vx, -(25 + rnd() * 30), 2 + rnd() * 1.5, fx.smokeSize + rnd() * 10);
    }
  }

  private advance(dt: number): void {
    for (const p of this.particles) {
      p.life += dt;
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      if (p.kind === "smoke") p.size += dt * 12;
      else if (p.kind === "debris") p.vy += 300 * dt;
      else if (p.kind === "flame") p.vy -= 60 * dt;
    }
    let w = 0;
    for (const p of this.particles) if (p.life < p.maxLife) this.particles[w++] = p;
    this.particles.length = w;
  }

  private emit(kind: ParticleKind, tone: ParticleTone, at: Point, vx: number, vy: number, maxLife: number, size: number): void {
    if (this.particles.length >= this.maxParticles) this.particles.shift();
    this.particles.push({ kind, tone, x: at.x, y: at.y, vx, vy, life: 0, maxLife, size });
  }
}
