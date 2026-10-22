/** Sprites em pixel art dos 4 carros: rasterização dentro da grelha, rodas animáveis e componente SVG. */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PixelArtCar } from "./PixelArtCar";
import { bodyRuns, CAR_SPRITES, rasterizeWheel, SPRITE_H, SPRITE_W, spriteFor } from "./sprites";

const IDS = ["hatch-20t-gdi", "coupe-30t-i6", "classic-20t-swap", "muscle-v8-sc"];

describe("sprites", () => {
  it("há um sprite por carro do catálogo, com pixels dentro da grelha", () => {
    expect(CAR_SPRITES.map((s) => s.id)).toEqual(IDS);
    for (const s of CAR_SPRITES) {
      const runs = [...bodyRuns(s), ...s.wheels.flatMap((w) => rasterizeWheel(s, w, 0))];
      expect(runs.length).toBeGreaterThan(100);
      for (const r of runs) {
        expect(r.x).toBeGreaterThanOrEqual(0);
        expect(r.y).toBeGreaterThanOrEqual(0);
        expect(r.x + r.w).toBeLessThanOrEqual(SPRITE_W);
        expect(r.y).toBeLessThan(SPRITE_H);
      }
    }
  });

  it("as rodas giram (pixels mudam com o ângulo) e a carroçaria queimada muda de cor", () => {
    const s = spriteFor("muscle-v8-sc");
    const a = JSON.stringify(rasterizeWheel(s, s.wheels[0], 0));
    const b = JSON.stringify(rasterizeWheel(s, s.wheels[0], 0.4));
    expect(a).not.toBe(b);
    expect(bodyRuns(s, true).some((r) => r.color === s.palette.body)).toBe(false);
  });

  it("IDs fora do catálogo caem no sprite mais próximo", () => {
    expect(spriteFor("muscle-v8-na").id).toBe("muscle-v8-sc");
    expect(spriteFor("coupe-x").id).toBe("coupe-30t-i6");
    expect(spriteFor(undefined).id).toBe("hatch-20t-gdi");
  });

  it("PixelArtCar desenha um SVG nítido, decorativo ou com rótulo", () => {
    const { container, rerender, getByRole } = render(<PixelArtCar vehicleId="classic-20t-swap" />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("data-sprite", "classic-20t-swap");
    expect(svg).toHaveAttribute("shape-rendering", "crispEdges");
    expect(svg.querySelectorAll("rect").length).toBeGreaterThan(100);
    rerender(<PixelArtCar vehicleId="classic-20t-swap" label="Clássico" />);
    expect(getByRole("img", { name: "Clássico" })).toBeInTheDocument();
  });
});
