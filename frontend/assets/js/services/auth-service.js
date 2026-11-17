import { APP_CONFIG } from "../config.js";
import { authApi } from "../api/auth-api.js";
import { authMockApi } from "../api/auth-mock.js";

export const authService = APP_CONFIG.authMode === "rest" ? authApi : authMockApi;
