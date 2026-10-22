/** Mocks partilhados do vitest (instalados em `src/test/setup.ts`). */
export {
  MockCanvasRenderingContext2D,
  createMockWebGLContext,
  installCanvasMock,
  resetCanvasMocks,
  setCanvasSupport,
} from "./canvas";
export type { CanvasSupport, ContextKind, RecordedCall } from "./canvas";
export {
  MockAudioContext,
  MockAudioParam,
  MockGainNode,
  MockOscillatorNode,
  installAudioMock,
  resetAudioMocks,
} from "./audio";
export { MockWebSocket, installWebSocketMock } from "./websocket";
export { installBrowserMocks } from "./browser";
