import { WS_PORT } from "./constants";

/** HTTP base for FastAPI (same host as WebSocket server, default port from constants.json). */
export function getApiBase(): string {
  const fromEnv = import.meta.env.VITE_API_BASE_URL;
  if (typeof fromEnv === "string" && fromEnv.trim()) {
    return fromEnv.replace(/\/$/, "");
  }
  return `http://127.0.0.1:${WS_PORT}`;
}
