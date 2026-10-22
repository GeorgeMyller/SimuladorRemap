/** Caminhos fixos do SPA (sem dependência das páginas lazy; usados pela casca e pelas features). */
export const ROUTE_PATHS = {
  home: "/",
  dyno: "/sessions/:sessionId/dyno",
  ecu: "/sessions/:sessionId/ecu",
  upgrades: "/sessions/:sessionId/upgrades",
  scenarios: "/scenarios/*",
  attempts: "/attempts/*",
  profiles: "/profiles",
  instructor: "/instructor",
  workshop: "/workshop",
} as const;

export const dynoPath = (sessionId: string) => `/sessions/${encodeURIComponent(sessionId)}/dyno`;
export const ecuPath = (sessionId: string) => `/sessions/${encodeURIComponent(sessionId)}/ecu`;
export const upgradesPath = (sessionId: string) => `/sessions/${encodeURIComponent(sessionId)}/upgrades`;
