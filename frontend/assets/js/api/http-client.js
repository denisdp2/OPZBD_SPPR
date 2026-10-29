import { APP_CONFIG } from "../config.js";

export class ApiError extends Error {
  constructor(message, { status = 0, detail = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function extractMessage(payload, fallback) {
  if (typeof payload?.detail === "string") return payload.detail;
  if (typeof payload?.message === "string") return payload.message;
  if (Array.isArray(payload?.detail)) {
    return payload.detail
      .map((item) => item?.msg)
      .filter(Boolean)
      .join("; ") || fallback;
  }
  return fallback;
}

/** Minimal JSON REST client shared by frontend API modules. */
export async function apiRequest(path, { method = "GET", body, headers = {}, signal } = {}) {
  const normalizedBase = APP_CONFIG.apiBaseUrl.replace(/\/$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const requestHeaders = new Headers({ Accept: "application/json", ...headers });
  const options = {
    method,
    headers: requestHeaders,
    credentials: "same-origin",
    signal,
  };

  if (body !== undefined) {
    requestHeaders.set("Content-Type", "application/json");
    options.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(`${normalizedBase}${normalizedPath}`, options);
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new ApiError("Не удалось связаться с сервером. Проверьте, запущено ли приложение.");
  }

  if (response.status === 204) return null;

  const contentType = response.headers.get("content-type") || "";
  let payload = null;
  if (contentType.includes("application/json")) {
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
  } else {
    const text = await response.text();
    if (text) payload = { detail: text };
  }

  if (!response.ok) {
    const fallback = response.status === 404
      ? "Эндпоинт не найден. Проверьте маршрут авторизации в FastAPI и в auth-api.js."
      : `Ошибка сервера (${response.status}). Попробуйте ещё раз.`;
    throw new ApiError(extractMessage(payload, fallback), {
      status: response.status,
      detail: payload?.detail ?? null,
    });
  }

  return payload;
}
