/**
 * Vista lateral do carro no rolo em Canvas 2D (RF-11, RF-21; D-12, D-22). Sprite em pixel art do
 * veículo da sessão (`features/pixel-cars`), sem marcas: rodas giram com o rolo e a carroçaria
 * vibra. A Visão Térmica / Raio-X (botão ou tecla T) deixa a carroçaria translúcida e mostra
 * coletor, turbina (ou compressor) e escape coloridos pela EGT.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { bodyRuns, paintRuns, rasterizeWheel, SPRITE_H, SPRITE_W, spriteFor, type CarSprite } from "@/features/pixel-cars/sprites";
import { formatNumber } from "@/lib/units";

import { isPlainShortcut } from "./keyboardTargets";
import { MSG } from "./messages";
import { CarAnimator, DEGRADED_PARTICLES, MAX_PARTICLES } from "./render/CarAnimator";
import { drawParticles } from "./render/drawParticles";
import type { RenderLoop } from "./render/RenderLoop";
import { drawThermalLayer, hotSpot, thermalCss, type ThermalGeometry, type ThermalTemps } from "./render/thermal";
import type { TelemetryStore } from "./store";
import { toggleThermalView, useThermalView } from "./thermalView";

export interface CarOnRollerViewProps {
  store: TelemetryStore;
  loop?: RenderLoop;
  maxRpm: number;
  /** Veículo da sessão (escolhe o sprite). */
  vehicleId?: string;
  /** Falha catastrófica recebida (`event.failure`); a chave muda a cada falha. */
  failureSeq?: number | null;
  /** Modo da falha; por omissão, o da última `event.failure` no store. */
  failureMode?: string | null;
  degraded?: boolean;
  animator?: CarAnimator;
  width?: number;
  height?: number;
}

const W = 480;
const H = 240;

/** Escala inteira do sprite na cena e posição do carro (rodas assentes nos rolos). */
const SCALE = 5;
const GROUND_Y = 198;
const ROLLER_Y = 214;
const ROLLER_R = 18;

/** Opacidade da carroçaria na Visão Térmica / Raio-X. */
const XRAY_BODY_ALPHA = 0.3;

export function carPlacement(sprite: CarSprite): { x: number; y: number; scale: number; rollers: number[] } {
  const x = Math.round((W - SPRITE_W * SCALE) / 2);
  const y = GROUND_Y - (SPRITE_H - 1) * SCALE;
  return { x, y, scale: SCALE, rollers: sprite.wheels.map((wh) => x + wh.x * SCALE) };
}

const geometryCache = new WeakMap<CarSprite, ThermalGeometry>();

/** Geometria da camada térmica no referencial da cena (pontos do sprite × escala), em cache por sprite. */
export function thermalGeometry(sprite: CarSprite): ThermalGeometry {
  const cached = geometryCache.get(sprite);
  if (cached) return cached;
  const p = carPlacement(sprite);
  const geometry: ThermalGeometry = {
    engine: { x: p.x + sprite.engineBay[0] * p.scale, y: p.y + sprite.engineBay[1] * p.scale },
    exhaust: { x: p.x + sprite.exhaust[0] * p.scale, y: p.y + sprite.exhaust[1] * p.scale },
    scale: p.scale,
    induction: sprite.induction,
  };
  geometryCache.set(sprite, geometry);
  return geometry;
}

/** Brilho residual no ponto quente após falhas térmicas (sobretemperatura, fusão do turbo). */
function drawHeatGlow(ctx: CanvasRenderingContext2D, a: CarAnimator): void {
  if (a.heatGlow <= 0) return;
  ctx.globalAlpha = 0.5 * a.heatGlow;
  ctx.fillStyle = thermalCss(900 + 100 * a.heatGlow);
  ctx.beginPath();
  ctx.arc(a.turbo.x, a.turbo.y, 10 + 10 * a.heatGlow, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;
}

/**
 * Desenha uma frame da animação (exportado para testes de desenho). Com `thermal`, a carroçaria
 * fica translúcida e a camada térmica é desenhada por cima dela.
 */
export function drawCarScene(ctx: CanvasRenderingContext2D, a: CarAnimator, w = W, h = H, sprite: CarSprite = spriteFor(null), thermal: ThermalTemps | null = null): void {
  const sx = w / W;
  const sy = h / H;
  const place = carPlacement(sprite);
  ctx.save();
  ctx.setTransform(sx, 0, 0, sy, 0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = "#09090b";
  ctx.fillRect(0, 0, W, H);
  // Chão (faixas de 5 px, como o sprite) e rolos.
  ctx.fillStyle = "#27272a";
  ctx.fillRect(0, GROUND_Y + 2, W, H - GROUND_Y - 2);
  ctx.fillStyle = "#3f3f46";
  ctx.fillRect(0, GROUND_Y + 2, W, SCALE);
  for (const rx of place.rollers) {
    ctx.fillStyle = "#3f3f46";
    ctx.beginPath();
    ctx.arc(rx, ROLLER_Y, ROLLER_R, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#a1a1aa";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(rx, ROLLER_Y);
    ctx.lineTo(rx + Math.cos(a.rollerAngle) * 16, ROLLER_Y + Math.sin(a.rollerAngle) * 16);
    ctx.stroke();
  }
  // Carroçaria com vibração vertical (arredondada ao pixel do ecrã para manter o aspeto nítido).
  const dy = Math.round(a.vibrationOffset);
  const burnt = a.exploded;
  if (thermal) ctx.globalAlpha = XRAY_BODY_ALPHA;
  paintRuns(ctx, bodyRuns(sprite, burnt), place.x, place.y + dy, place.scale);
  ctx.globalAlpha = 1;
  for (const wheel of sprite.wheels) {
    paintRuns(ctx, rasterizeWheel(sprite, wheel, a.wheelAngle), place.x, place.y + Math.round(dy * 0.3), place.scale);
  }
  if (thermal) {
    ctx.translate(0, dy);
    drawThermalLayer(ctx, thermalGeometry(sprite), thermal);
    ctx.translate(0, -dy);
  }
  drawHeatGlow(ctx, a);
  drawParticles(ctx, a);
  // Explosão: um único clarão que decai (≤ 3 flashes/s garantidos pelo FlashLimiter).
  if (a.explosionFlash > 0) {
    ctx.fillStyle = `rgba(254,215,170,${0.5 * a.explosionFlash})`;
    ctx.beginPath();
    ctx.arc(a.engineBay.x, a.engineBay.y, 60 + 40 * (1 - a.explosionFlash), 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

/** Modo da última falha registada no store (`event.failure`). */
function lastFailureMode(store: TelemetryStore): string | null {
  for (let i = store.events.length - 1; i >= 0; i -= 1) {
    const mode = store.events[i]!.failure?.mode;
    if (mode) return mode;
  }
  return null;
}

/** Tecla T liga/desliga a visão térmica (fora de campos de texto e com nenhum diálogo aberto). */
function useThermalShortcut(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key !== "t" && e.key !== "T") || !isPlainShortcut(e) || e.repeat) return;
      if (document.querySelector('[role="dialog"]')) return;
      e.preventDefault();
      toggleThermalView();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

const TOGGLE_BASE =
  "absolute right-2 top-2 rounded-sm border px-2 py-1 font-mono text-[11px] font-semibold uppercase tracking-wide motion-safe:transition-colors active:translate-y-px focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white";
const TOGGLE_ON = "border-amber-300 bg-amber-400 text-zinc-950 hover:bg-amber-300";
const TOGGLE_OFF = "border-zinc-600 bg-zinc-950/85 text-zinc-100 hover:border-amber-300 hover:text-amber-200";

export function CarOnRollerView({ store, loop, maxRpm, vehicleId, failureSeq = null, failureMode, degraded = false, animator, width = W, height = H }: CarOnRollerViewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<CarAnimator | null>(null);
  const [speedText, setSpeedText] = useState("0");
  const sprite = spriteFor(vehicleId);
  const thermalOn = useThermalView();
  useThermalShortcut();
  const getAnim = useCallback((): CarAnimator => {
    if (!animRef.current) animRef.current = animator ?? new CarAnimator();
    return animRef.current;
  }, [animator]);

  useEffect(() => {
    const g = thermalGeometry(sprite);
    getAnim().configure({ exhaust: g.exhaust, engineBay: g.engine, turbo: hotSpot(g) });
  }, [getAnim, sprite]);

  useEffect(() => {
    getAnim().configure({ maxParticles: degraded ? DEGRADED_PARTICLES : MAX_PARTICLES });
  }, [getAnim, degraded]);

  useEffect(() => {
    if (failureSeq === null) getAnim().reset();
    else getAnim().triggerFailure(failureSeq, failureMode ?? lastFailureMode(store));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a falha dispara pela chave `failureSeq`
  }, [getAnim, failureSeq]);

  useEffect(() => {
    if (!loop) return;
    const anim = getAnim();
    let cursor = store.afterfireTotal;
    let lastUi = -Infinity;
    const temps: ThermalTemps = { egtC: null, egtPreTurboC: null };
    return loop.add((now, dtMs) => {
      const fire = store.afterfireSince(cursor);
      cursor = fire.total;
      const speed = store.value("roller_speed_kmh") ?? 0;
      anim.step(dtMs / 1000, {
        rollerSpeedKmh: speed,
        rpm: store.value("rpm") ?? 0,
        maxRpm,
        throttlePct: store.value("throttle_pct") ?? 0,
        afterfire: fire.count,
        afterfireSeq: fire.seq,
      });
      const ctx = canvasRef.current?.getContext("2d");
      if (thermalOn) {
        temps.egtC = store.value("egt_c") ?? null;
        temps.egtPreTurboC = store.value("egt_pre_turbo_c") ?? null;
      }
      if (ctx) drawCarScene(ctx, anim, canvasRef.current!.width, canvasRef.current!.height, sprite, thermalOn ? temps : null);
      if (now - lastUi > 250) {
        lastUi = now;
        setSpeedText(formatNumber(speed, 0));
      }
    });
  }, [loop, store, getAnim, maxRpm, sprite, thermalOn]);

  return (
    <figure aria-labelledby="car-title" className="m-0">
      <figcaption id="car-title" className="mb-1 flex items-center gap-3 text-sm text-zinc-200">
        <span className="font-semibold">Carro no rolo</span>
        <span className="font-mono text-xs text-zinc-300" data-testid="roller-speed">
          rolo {speedText} km/h
        </span>
      </figcaption>
      <div className="relative">
        <canvas
          ref={canvasRef}
          width={width}
          height={height}
          role="img"
          aria-label={`${failureSeq !== null ? `${sprite.name} no rolo com fumaça: motor destruído` : `${sprite.name} no rolo do dinamômetro`}${thermalOn ? `. ${MSG.thermalViewOn}` : ""}`}
          data-sprite={sprite.id}
          data-thermal={thermalOn ? "on" : "off"}
          className="h-auto w-full rounded bg-black [image-rendering:pixelated]"
        />
        <button type="button" aria-pressed={thermalOn} aria-keyshortcuts="t" title={`${MSG.thermalView} (T)`} onClick={toggleThermalView} className={`${TOGGLE_BASE} ${thermalOn ? TOGGLE_ON : TOGGLE_OFF}`}>
          {MSG.thermalView}
        </button>
      </div>
    </figure>
  );
}
