/**
 * Ilustração em pixel art (SVG, `crispEdges`) de um carro do catálogo, para os cards da tela
 * inicial. Decorativa por omissão; com `label` passa a `role="img"`.
 */
import { useMemo } from "react";

import { bodyRuns, rasterizeWheel, SPRITE_H, SPRITE_W, spriteFor, type PixelRun } from "./sprites";

export interface PixelArtCarProps {
  vehicleId: string;
  /** Ângulo das rodas (rad). */
  wheelAngle?: number;
  label?: string;
  className?: string;
}

function Runs({ runs }: { runs: readonly PixelRun[] }) {
  return (
    <>
      {runs.map((r) => (
        <rect key={`${r.x},${r.y}`} x={r.x} y={r.y} width={r.w} height={1} fill={r.color} />
      ))}
    </>
  );
}

export function PixelArtCar({ vehicleId, wheelAngle = 0, label, className }: PixelArtCarProps) {
  const sprite = spriteFor(vehicleId);
  const body = bodyRuns(sprite);
  const wheels = useMemo(() => sprite.wheels.map((w) => rasterizeWheel(sprite, w, wheelAngle)), [sprite, wheelAngle]);
  return (
    <svg
      viewBox={`0 0 ${SPRITE_W} ${SPRITE_H}`}
      shapeRendering="crispEdges"
      data-sprite={sprite.id}
      className={className}
      style={{ imageRendering: "pixelated" }}
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true, focusable: false })}
    >
      <Runs runs={body} />
      {wheels.map((runs, i) => (
        <g key={i}>
          <Runs runs={runs} />
        </g>
      ))}
    </svg>
  );
}
