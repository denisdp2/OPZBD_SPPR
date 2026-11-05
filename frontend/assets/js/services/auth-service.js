import { APP_CONFIG } from "../config.js";
import { authApi } from "../api/auth-api.js";
import { authMockApi } from "../api/auth-mock.js";

/** Keeps page code independent from whether auth is mocked or served by REST. */
export const authService = APP_CONFIG.authMode === "rest" ? authApi : authMockApi;
