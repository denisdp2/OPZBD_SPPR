import { APP_CONFIG } from "../config.js";
import { apiRequest } from "./http-client.js";

const request = (path, options = {}) => apiRequest(path, {
  ...options,
  baseUrl: APP_CONFIG.workspaceApiBaseUrl,
});

/** REST endpoints already declared by the FastAPI app. */
export const workspaceApi = Object.freeze({
  health: () => request("/health"),
  requirements: () => request("/requirements"),
  items: () => request("/items"),
  profiles: () => request("/profiles"),
  optimizers: () => request("/optimizers"),
  evaluate: (scenario) => request("/evaluate", { method: "POST", body: scenario }),
  optimize: (payload) => request("/optimize", { method: "POST", body: payload }),
  pareto: (payload) => request("/pareto", { method: "POST", body: payload }),
});
