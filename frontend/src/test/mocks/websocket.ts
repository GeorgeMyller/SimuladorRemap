/**
 * Mock de WebSocket para o vitest (cockpit RF-02, RF-04, RF-05; D-19).
 * Cada `new WebSocket(url)` fica em `MockWebSocket.instances`; o teste controla o servidor:
 * `ws.open()`, `ws.receive({...})` (objetos viram JSON), `ws.serverClose(1011)`, `ws.fail()`.
 * As mensagens do cliente ficam em `ws.sent` (`ws.sentJson()` faz o parse).
 */

export class MockWebSocket extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: MockWebSocket[] = [];

  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSING = 2;
  readonly CLOSED = 3;

  readonly url: string;
  readonly protocol: string;
  readyState: number = MockWebSocket.CONNECTING;
  binaryType: BinaryType = "blob";
  bufferedAmount = 0;
  extensions = "";
  readonly sent: (string | ArrayBufferLike | Blob | ArrayBufferView)[] = [];
  closeCode: number | null = null;
  closeReason = "";

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: string | URL, protocols?: string | string[]) {
    super();
    this.url = String(url);
    this.protocol = Array.isArray(protocols) ? (protocols[0] ?? "") : (protocols ?? "");
    MockWebSocket.instances.push(this);
  }

  static last(): MockWebSocket | undefined {
    return MockWebSocket.instances.at(-1);
  }

  static reset(): void {
    MockWebSocket.instances = [];
  }

  private emit(event: Event): void {
    this.dispatchEvent(event);
    const handler = (this as unknown as Record<string, ((e: Event) => void) | null>)[
      `on${event.type}`
    ];
    handler?.call(this, event);
  }

  send(data: string | ArrayBufferLike | Blob | ArrayBufferView): void {
    if (this.readyState !== MockWebSocket.OPEN) {
      throw new DOMException("WebSocket não está aberto", "InvalidStateError");
    }
    this.sent.push(data);
  }

  close(code = 1000, reason = ""): void {
    if (this.readyState === MockWebSocket.CLOSED) return;
    this.readyState = MockWebSocket.CLOSING;
    this.finishClose(code, reason, true);
  }

  // ---------------------------------------------------------------- controlo do servidor
  open(): void {
    this.readyState = MockWebSocket.OPEN;
    this.emit(new Event("open"));
  }

  receive(data: unknown): void {
    const payload = typeof data === "string" || data instanceof ArrayBuffer ? data : JSON.stringify(data);
    this.emit(new MessageEvent("message", { data: payload }));
  }

  serverClose(code = 1006, reason = ""): void {
    this.finishClose(code, reason, code === 1000);
  }

  fail(): void {
    this.emit(new Event("error"));
    this.finishClose(1006, "", false);
  }

  sentJson(): unknown[] {
    return this.sent.filter((m): m is string => typeof m === "string").map((m) => JSON.parse(m) as unknown);
  }

  private finishClose(code: number, reason: string, wasClean: boolean): void {
    this.readyState = MockWebSocket.CLOSED;
    this.closeCode = code;
    this.closeReason = reason;
    this.emit(new CloseEvent("close", { code, reason, wasClean }));
  }
}

export function installWebSocketMock(): void {
  Object.defineProperty(globalThis, "WebSocket", {
    configurable: true,
    writable: true,
    value: MockWebSocket,
  });
}
