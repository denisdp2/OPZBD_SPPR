/**
 * Demo-only auth provider. Data lives in memory and disappears on page reload.
 * This module is not suitable for production authentication.
 */
const accounts = new Map();

function normalizeLogin(login) {
  return String(login ?? "").trim().toLowerCase();
}

function waitForDemoResponse() {
  return new Promise((resolve) => window.setTimeout(resolve, 180));
}

export const authMockApi = Object.freeze({
  async register({ login, password }) {
    await waitForDemoResponse();
    const normalizedLogin = normalizeLogin(login);

    if (normalizedLogin.length < 3) {
      throw new Error("Логин должен содержать не менее 3 символов.");
    }
    if (String(password ?? "").length < 8) {
      throw new Error("Пароль должен содержать не менее 8 символов.");
    }
    if (accounts.has(normalizedLogin)) {
      throw new Error("Этот логин уже зарегистрирован.");
    }

    accounts.set(normalizedLogin, String(password));
    return { message: "Аккаунт создан. Теперь можно войти." };
  },

  async login({ login, password }) {
    await waitForDemoResponse();
    const savedPassword = accounts.get(normalizeLogin(login));

    if (savedPassword === undefined || savedPassword !== String(password ?? "")) {
      throw new Error("Неверный логин или пароль.");
    }

    return { message: "Вход выполнен." };
  },

  async requestPasswordReset({ login }) {
    await waitForDemoResponse();
    // Generic response avoids revealing whether a particular account exists.
    return {
      message: "Запрос принят.",
    };
  },
});
