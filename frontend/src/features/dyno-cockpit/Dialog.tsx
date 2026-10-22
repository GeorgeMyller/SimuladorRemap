/** Diálogo modal acessível: `role="dialog"`, foco preso, `Esc` fecha e o foco volta à origem. */
import { useEffect, useRef, type ReactNode } from "react";

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

export interface DialogProps {
  titleId: string;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  className?: string;
  fullScreen?: boolean;
}

export function Dialog({ titleId, title, onClose, children, className = "", fullScreen = false }: DialogProps) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const first = el?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? el)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (!el) return;
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = [...el.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const firstItem = items[0]!;
      const lastItem = items[items.length - 1]!;
      if (e.shiftKey && document.activeElement === firstItem) {
        e.preventDefault();
        lastItem.focus();
      } else if (!e.shiftKey && document.activeElement === lastItem) {
        e.preventDefault();
        firstItem.focus();
      }
    };
    el?.addEventListener("keydown", onKey);
    return () => {
      el?.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" data-dialog-backdrop>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`${fullScreen ? "h-[95vh] w-[96vw]" : "max-w-lg"} overflow-auto rounded-lg border border-zinc-600 bg-zinc-900 p-4 text-zinc-100 shadow-xl focus:outline-none ${className}`}
      >
        <div className="mb-3 flex items-center justify-between gap-4">
          <h2 id={titleId} className="text-lg font-semibold">
            {title}
          </h2>
          <button
            type="button"
            onClick={() => closeRef.current()}
            className="rounded border border-zinc-500 px-2 py-1 text-sm hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400"
          >
            Fechar
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
