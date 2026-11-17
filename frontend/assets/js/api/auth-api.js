import { apiRequest } from "./http-client.js";

// Восстановление пароля пока не реализовано на сервере.
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
