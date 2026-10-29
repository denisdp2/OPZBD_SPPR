import { apiRequest } from "./http-client.js";

/**
 * REST contract proposed for the auth module.
 * Confirm these routes and request/response schemas against FastAPI /docs
 * before switching authMode to "rest".
 */
export const authApi = Object.freeze({
  register({ login, password }) {
    return apiRequest("/auth/register", {
      method: "POST",
      body: { login, password },
    });
  },

  login({ login, password }) {
    return apiRequest("/auth/login", {
      method: "POST",
      body: { login, password },
    });
  },

  requestPasswordReset({ login }) {
    return apiRequest("/auth/password-reset/request", {
      method: "POST",
      body: { login },
    });
  },
});
