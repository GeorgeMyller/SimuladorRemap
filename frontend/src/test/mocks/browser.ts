/** Polyfills de APIs do navegador ausentes no jsdom (rAF, matchMedia, ResizeObserver). */

let rafId = 0;
const rafTimers = new Map<number, ReturnType<typeof setTimeout>>();

export function installBrowserMocks(): void {
  if (typeof globalThis.requestAnimationFrame !== "function") {
    globalThis.requestAnimationFrame = (callback: FrameRequestCallback): number => {
      const id = ++rafId;
      rafTimers.set(
        id,
        setTimeout(() => {
          rafTimers.delete(id);
          callback(performance.now());
        }, 16),
      );
      return id;
    };
    globalThis.cancelAnimationFrame = (id: number): void => {
      clearTimeout(rafTimers.get(id));
      rafTimers.delete(id);
    };
  }
  if (typeof window.matchMedia !== "function") {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: (query: string): MediaQueryList =>
        ({
          matches: false,
          media: query,
          onchange: null,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
          addListener: () => undefined,
          removeListener: () => undefined,
          dispatchEvent: () => false,
        }) as MediaQueryList,
    });
  }
  if (typeof globalThis.ResizeObserver !== "function") {
    class MockResizeObserver {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    }
    globalThis.ResizeObserver = MockResizeObserver;
  }
}
