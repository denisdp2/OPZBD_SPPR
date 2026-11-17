import { APP_CONFIG } from "../config.js";
import { apiRequest } from "./http-client.js";

const request = (path, options = {}) => apiRequest(path, {
  ...options,
  baseUrl: APP_CONFIG.workspaceApiBaseUrl,
});

export const workspaceApi = Object.freeze({
  health: () => request("/health"),
  requirements: () => request("/requirements"),
  items: () => request("/items"),
  profiles: () => request("/profiles"),
  optimizers: () => request("/optimizers"),
  evaluate: (scenario) => request("/evaluate", { method: "POST", body: scenario }),
  optimize: (payload, signal) => request("/optimize", { method: "POST", body: payload, signal }),
  pareto: (payload, signal) => request("/pareto", { method: "POST", body: payload, signal }),
  cancelOptimization: () => request("/optimize/cancel", { method: "POST" }),
});
