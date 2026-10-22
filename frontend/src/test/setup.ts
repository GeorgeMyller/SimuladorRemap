/**
 * Setup do vitest (cockpit RNF-09): jest-dom, limpeza do DOM e mocks de Canvas 2D,
 * WebGL/WebGL2, Web Audio, WebSocket, requestAnimationFrame, matchMedia e ResizeObserver.
 * Os helpers de controlo ficam em `@/test/mocks` (ex.: `setCanvasSupport`, `MockWebSocket`).
 */
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import {
  MockWebSocket,
  installAudioMock,
  installBrowserMocks,
  installCanvasMock,
  installWebSocketMock,
  resetAudioMocks,
  resetCanvasMocks,
} from "./mocks";

installBrowserMocks();
installCanvasMock();
installAudioMock();
installWebSocketMock();

afterEach(() => {
  cleanup();
  resetCanvasMocks();
  resetAudioMocks();
  MockWebSocket.reset();
});
