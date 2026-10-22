/**
 * `true` enquanto a janela tem pelo menos `px` de largura (acompanha `resize`). Sem `window` (SSR)
 * assume o ecrã largo.
 */
import { useEffect, useState } from "react";

/** Breakpoint `lg` do Tailwind. */
export const LG_PX = 1024;

export function useMinWidth(px: number): boolean {
  const [wide, setWide] = useState(() => (typeof window === "undefined" ? true : window.innerWidth >= px));
  useEffect(() => {
    const onResize = () => setWide(window.innerWidth >= px);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [px]);
  return wide;
}
