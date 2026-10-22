/** Alvos de teclado que recebem texto: atalhos globais da bancada não devem agir neles. */
export function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el?.tagName) return false;
  const tag = el.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable) return true;
  if (tag === "INPUT") {
    const type = (el as HTMLInputElement).type;
    return type !== "range" && type !== "button" && type !== "checkbox" && type !== "radio";
  }
  return false;
}

/** Atalho de tecla simples: sem Ctrl/Meta/Alt, não tratado antes e fora de campos de texto. */
export function isPlainShortcut(e: KeyboardEvent): boolean {
  return !e.defaultPrevented && !e.ctrlKey && !e.metaKey && !e.altKey && !isTypingTarget(e.target);
}
