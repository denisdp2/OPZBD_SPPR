import { APP_CONFIG } from "../config.js";
import { ApiError } from "../api/http-client.js";
import { authService } from "../services/auth-service.js";

const views = {
  login: document.querySelector("#login-view"),
  register: document.querySelector("#register-view"),
  forgot: document.querySelector("#forgot-view"),
};
const tabs = [...document.querySelectorAll(".auth-tab")];

function showView(name) {
  if (!Object.hasOwn(views, name)) return;

  Object.entries(views).forEach(([key, section]) => {
    const active = key === name;
    section.hidden = !active;
    section.classList.toggle("is-visible", active);
  });

  tabs.forEach((tab) => {
    const active = tab.dataset.view === name;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });

  const titles = { login: "Вход", register: "Регистрация", forgot: "Восстановление доступа" };
  document.title = titles[name];
  const focusTarget = views[name].querySelector("input");
  if (focusTarget) window.setTimeout(() => focusTarget.focus(), 50);
}

function showMessage(formId, message, type = "info") {
  const messageBox = document.querySelector(`#${formId}-message`);
  if (!messageBox) return;
  messageBox.textContent = message;
  messageBox.className = `form-message${type === "error" ? " is-error" : type === "success" ? " is-success" : ""}`;
  messageBox.hidden = false;
}

function clearMessage(formId) {
  const messageBox = document.querySelector(`#${formId}-message`);
  if (!messageBox) return;
  messageBox.hidden = true;
  messageBox.textContent = "";
  messageBox.className = "form-message";
}

function readField(form, name) {
  return String(new FormData(form).get(name) ?? "").trim();
}

function errorMessage(error) {
  if (error instanceof ApiError && error.status === 404) {
    return `${error.message} Пока можно оставить authMode: "mock" в assets/js/config.js.`;
  }
  return error?.message || "Не удалось выполнить запрос. Попробуйте ещё раз.";
}

async function runFormAction(form, formId, action, onSuccess) {
  clearMessage(formId);
  if (!form.reportValidity()) return;

  const submitButton = form.querySelector('button[type="submit"]');
  if (submitButton) submitButton.disabled = true;

  try {
    const result = await action();
    await onSuccess(result);
  } catch (error) {
    showMessage(formId, errorMessage(error), "error");
  } finally {
    if (submitButton) submitButton.disabled = false;
  }
}

for (const control of document.querySelectorAll("[data-view]")) {
  control.addEventListener("click", () => {
    ["login", "register", "forgot"].forEach(clearMessage);
    showView(control.dataset.view);
  });
}

for (const button of document.querySelectorAll("[data-password-toggle]")) {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.passwordToggle);
    if (!input) return;
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.textContent = show ? "Скрыть" : "Показать";
    button.setAttribute("aria-label", show ? "Скрыть пароль" : "Показать пароль");
    input.focus();
  });
}

document.querySelector("#login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  runFormAction(form, "login", () => authService.login({
    login: readField(form, "login"),
    password: String(new FormData(form).get("password") ?? ""),
  }), (result) => {
    showMessage("login", result?.message || "Вход выполнен.", "success");
    window.setTimeout(() => window.location.assign("/static/workspace.html"), 850);
  });
});

document.querySelector("#register-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const login = readField(form, "login");
  const password = String(new FormData(form).get("password") ?? "");

  runFormAction(form, "register", () => authService.register({ login, password }), (result) => {
    form.reset();
    showView("login");
    document.querySelector("#login-name").value = login;
    showMessage("login", result?.message || "Регистрация успешно завершена. Теперь войдите.", "success");
  });
});

document.querySelector("#forgot-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  runFormAction(form, "forgot", () => authService.requestPasswordReset({
    login: readField(form, "login"),
  }), (result) => {
    showMessage("forgot", result?.message || "Если для этого логина доступно восстановление, дальнейшие инструкции будут отправлены по настроенному каналу.", "info");
  });
});

showView("login");
