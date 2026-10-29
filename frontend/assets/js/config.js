/**
 * Frontend configuration.
 * Set authMode to "rest" only after matching endpoints exist in the FastAPI app.
 */
export const APP_CONFIG = Object.freeze({
  apiBaseUrl: "/api/v1",
  authMode: "mock", // "mock" | "rest"
});
