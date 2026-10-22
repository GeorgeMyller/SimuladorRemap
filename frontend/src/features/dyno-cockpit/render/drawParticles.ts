/** Desenho das partículas e do clarão do escape do carro no rolo (estilos fixos por tom). */
import type { CarAnimator } from "./CarAnimator";
import { TONE_STYLE } from "./failureFx";

const EXHAUST_FLASH_COLOR = "#fdba74";

export function drawParticles(ctx: CanvasRenderingContext2D, a: CarAnimator): void {
  if (a.exhaustFlash > 0) {
    ctx.globalAlpha = 0.45 * a.exhaustFlash;
    ctx.fillStyle = EXHAUST_FLASH_COLOR;
    ctx.beginPath();
    ctx.arc(a.exhaust.x - 6, a.exhaust.y, 10 + 8 * a.exhaustFlash, 0, Math.PI * 2);
    ctx.fill();
  }
  for (const p of a.particles) {
    const k = 1 - p.life / p.maxLife;
    const style = TONE_STYLE[p.tone];
    ctx.globalAlpha = style.alpha * k;
    ctx.fillStyle = style.color;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.kind === "flame" ? p.size * (0.5 + 0.5 * k) : p.size, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}
