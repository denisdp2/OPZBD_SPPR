const pages = [...document.querySelectorAll("main section")];
const navButtons = [...document.querySelectorAll("nav button")];

function showFlash(root, message, ok = false) {
  let box = root.querySelector(".flash");
  if (!box) {
    box = document.createElement("div");
    box.className = "flash";
    root.prepend(box);
  }
  box.textContent = message;
  box.classList.add("show");
  box.classList.toggle("ok", ok);
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

function csvList(value) {
  return String(value || "")
    .split(/[,;\n]/)
    .map((part) => part.trim())
    .filter(Boolean);
}

function table(headers, rows) {
  if (!rows.length) return `<div class="card">Записей нет.</div>`;
  return `<table><thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.join("")}</tbody></table>`;
}

function showPage(id) {
  pages.forEach((page) => page.classList.toggle("hidden", page.id !== `page-${id}`));
  navButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.page === id));
  if (id === "dashboard") loadDashboard();
  if (id === "requirements") loadRequirements();
  if (id === "tools") loadTools();
  if (id === "org") loadOrg();
  if (id === "gaps") loadGaps();
  if (id === "registry") { loadRegistry(); pollPrices(); }
}

async function loadList(path) {
  return SZI.request(path);
}

function renderError(target, err) {
  target.innerHTML = `<div class="card">${esc(err.message)}</div>`;
}

async function loadDashboard() {
  const set = (id, value) => {
    document.getElementById(id).textContent = value;
  };
  try {
    set("stat-req", (await loadList("/api/requirements")).length);
  } catch (err) {
    set("stat-req", "н/д");
  }
  try {
    const items = await loadList("/api/items");
    set("stat-tools", items.filter((item) => item.kind !== "org").length);
    set("stat-org", items.filter((item) => item.kind === "org").length);
  } catch {
    set("stat-tools", "н/д");
    set("stat-org", "н/д");
  }
  try {
    set("stat-gaps", (await SZI.request("/api/admin/gaps")).length);
  } catch {
    set("stat-gaps", "н/д");
  }
}

function bindCrud({ tableId, formId, listPath, itemPath, columns, formHtml, toPayload, toRow, filter }) {
  const tableRoot = document.getElementById(tableId);
  const formRoot = document.getElementById(formId);
  let cached = [];
  let offset = 0;
  let query = "";

  async function refresh(reload = true) {
    try {
      if (reload) cached = await loadList(listPath);
      let items = filter ? cached.filter(filter) : cached;
      if (query) items = items.filter(item =>
        [item.id, item.name, item.title, item.vendor].join(" ").toLocaleLowerCase().includes(query.toLocaleLowerCase()));
      if (offset >= items.length) offset = Math.max(0, Math.floor((items.length - 1) / 50) * 50);
      tableRoot.innerHTML = `<form data-catalog-search class="card toolbar">
          <label for="${tableId}-query">Поиск по коду или названию</label>
          <input id="${tableId}-query" name="q" type="search" value="${esc(query)}">
          <button class="btn secondary" type="submit">Найти</button></form>` + table(
        columns, items.slice(offset, offset + 50).map((item) => toRow(item)),
      ) + `<div class="toolbar"><button class="btn secondary" data-prev ${offset === 0 ? "disabled" : ""}>Назад</button>
        <span>${items.length ? `${offset + 1}–${Math.min(offset + 50, items.length)} из ${items.length}` : "Нет записей"}</span>
        <button class="btn secondary" data-next ${offset + 50 >= items.length ? "disabled" : ""}>Далее</button></div>`;
    } catch (err) {
      renderError(tableRoot, err);
    }
  }

  function openForm(values = {}) {
    formRoot.classList.remove("hidden");
    formRoot.innerHTML = formHtml(values);
    formRoot.querySelector("form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = toPayload(new FormData(event.target));
      try {
        await SZI.request(itemPath(data.id), {
          method: "PUT",
          body: JSON.stringify(data),
        });
        formRoot.classList.add("hidden");
        await refresh();
      } catch (err) {
        showFlash(formRoot, err.message);
      }
    });
    formRoot.querySelector("[data-cancel]").addEventListener("click", () => {
      formRoot.classList.add("hidden");
    });
  }

  tableRoot.addEventListener("click", async (event) => {
    const btn = event.target.closest("button");
    if (!btn) return;
    if (btn.hasAttribute("data-prev")) { offset = Math.max(0, offset - 50); await refresh(false); return; }
    if (btn.hasAttribute("data-next")) { offset += 50; await refresh(false); return; }
    const id = btn.dataset.id;
    if (btn.hasAttribute("data-edit")) {
      try {
        const item = await SZI.request(itemPath(id));
        openForm(item);
      } catch (err) {
        renderError(tableRoot, err);
      }
    }
    if (btn.hasAttribute("data-delete")) {
      if (!confirm(`Удалить «${id}»?`)) return;
      try {
        await SZI.request(itemPath(id), { method: "DELETE" });
        await refresh();
      } catch (err) {
        renderError(tableRoot, err);
      }
    }
  });

  tableRoot.addEventListener("submit", event => {
    if (!event.target.matches("[data-catalog-search]")) return;
    event.preventDefault();
    query = new FormData(event.target).get("q").trim();
    offset = 0;
    refresh(false);
  });
  return { refresh, openForm };
}

const requirementsUi = bindCrud({
  tableId: "req-table",
  formId: "req-form",
  listPath: "/api/requirements",
  itemPath: (id) => `/api/admin/requirements/${encodeURIComponent(id)}`,
  columns: ["Код", "Группа", "Название", "Источник", ""],
  formHtml: (v) => `
    <form>
      <div class="form-grid">
        <div><label>Код</label><input name="id" value="${esc(v.id)}" ${v.id ? "readonly" : ""} required></div>
        <div><label>Группа</label><input name="group" value="${esc(v.group)}"></div>
        <div class="span-2"><label>Название</label><input name="title" value="${esc(v.title)}" required></div>
        <div class="span-2"><label>Источник</label><input name="source" value="${esc(v.source)}"></div>
        <div class="span-2"><label>Описание</label><textarea name="description">${esc(v.description)}</textarea></div>
      </div>
      <div class="toolbar" style="margin-top:14px">
        <button class="btn" type="submit">Сохранить</button>
        <button class="btn secondary" type="button" data-cancel>Отмена</button>
      </div>
    </form>`,
  toPayload: (fd) => Object.fromEntries(fd.entries()),
  toRow: (item) => `<tr>
      <td>${esc(item.id)}</td><td>${esc(item.group)}</td><td>${esc(item.title)}</td><td>${esc(item.source)}</td>
      <td class="row-actions">
        <button class="btn secondary" data-edit data-id="${esc(item.id)}">Изменить</button>
        <button class="btn danger" data-delete data-id="${esc(item.id)}">Удалить</button>
      </td></tr>`,
});

function itemFormHtml(v) {
  const kind = v.kind === "org" ? "org" : "tool";
  return `
    <form>
      <input type="hidden" name="kind" value="${esc(kind)}">
      <div class="form-grid">
        <div><label>Код</label><input name="id" value="${esc(v.id)}" ${v.id ? "readonly" : ""} required></div>
        <div class="span-2"><label>Название</label><input name="name" value="${esc(v.name)}" required></div>
        <div class="span-2"><label>Описание</label><textarea name="description">${esc(v.description)}</textarea></div>
        <div class="span-2"><label>Закрывает требования (через запятую)</label>
          <input name="covers" value="${esc((v.covers || []).join(", "))}"></div>
        <div><label>Производитель</label><input name="vendor" value="${esc(v.vendor)}"></div>
        <div><label>Срок внедрения, дни</label><input name="implement_days" type="number" min="0" step="0.1" value="${esc(v.implement_days)}"></div>
        <div><label><input type="checkbox" name="fstec_certified" ${v.fstec_certified ? "checked" : ""}> Сертификат ФСТЭК</label></div>
        <div><label>Номер сертификата</label><input name="fstec_cert_no" value="${esc(v.fstec_cert_no)}"></div>
        <div><label>Сертификат до</label><input name="fstec_cert_valid_until" type="date" value="${esc(v.fstec_cert_valid_until)}"></div>
        <div><label><input type="checkbox" name="in_ru_software_registry" ${v.in_ru_software_registry ? "checked" : ""}> Реестр российского ПО</label></div>
      </div>
      <div class="toolbar" style="margin-top:14px">
        <button class="btn" type="submit">Сохранить</button>
        <button class="btn secondary" type="button" data-cancel>Отмена</button>
      </div>
    </form>`;
}

function itemPayload(fd) {
  const data = Object.fromEntries(fd.entries());
  return {
    id: data.id,
    kind: data.kind,
    name: data.name,
    description: data.description || "",
    covers: csvList(data.covers),
    vendor: data.vendor || "",
    fstec_certified: fd.get("fstec_certified") === "on",
    fstec_cert_no: data.fstec_cert_no || null,
    fstec_cert_valid_until: data.fstec_cert_valid_until || null,
    in_ru_software_registry: fd.get("in_ru_software_registry") === "on",
    implement_days: data.implement_days === "" ? null : Number(data.implement_days),
  };
}

function itemRow(item) {
  return `<tr>
      <td>${esc(item.id)}</td>
      <td>${esc(item.name)}</td><td>${esc((item.covers || []).join(", "))}</td>
      <td class="row-actions">
        <button class="btn secondary" data-edit data-id="${esc(item.id)}">Изменить</button>
        <button class="btn danger" data-delete data-id="${esc(item.id)}">Удалить</button>
      </td></tr>`;
}

const toolsUi = bindCrud({
  tableId: "tool-table",
  formId: "tool-form",
  listPath: "/api/items",
  itemPath: (id) => `/api/admin/items/${encodeURIComponent(id)}`,
  columns: ["Код", "Название", "Закрывает", ""],
  filter: (item) => item.kind !== "org",
  formHtml: itemFormHtml,
  toPayload: itemPayload,
  toRow: itemRow,
});

const orgUi = bindCrud({
  tableId: "org-table",
  formId: "org-form",
  listPath: "/api/items",
  itemPath: (id) => `/api/admin/items/${encodeURIComponent(id)}`,
  columns: ["Код", "Название", "Закрывает", ""],
  filter: (item) => item.kind === "org",
  formHtml: itemFormHtml,
  toPayload: itemPayload,
  toRow: itemRow,
});

async function loadRequirements() {
  await requirementsUi.refresh();
}
async function loadTools() {
  await toolsUi.refresh();
}
async function loadOrg() {
  await orgUi.refresh();
}

async function loadGaps() {
  const root = document.getElementById("gaps-table");
  try {
    const items = await SZI.request("/api/admin/gaps");
    root.innerHTML = table(
      ["Код", "Название", "Источник"],
      items.map((item) => `<tr><td>${esc(item.id)}</td><td>${esc(item.title)}</td><td>${esc(item.source)}</td></tr>`),
    );
  } catch (err) {
    renderError(root, err);
  }
}

navButtons.forEach((btn) => {
  btn.addEventListener("click", () => showPage(btn.dataset.page));
});

document.querySelectorAll("[data-upload]").forEach((input) => {
  input.addEventListener("change", async () => {
    const status = document.querySelector(`[data-upload-status="${input.dataset.upload}"]`);
    const file = input.files && input.files[0];
    if (!file) {
      status.textContent = "Файл не выбран";
      return;
    }
    status.textContent = `Загрузка: ${file.name}`;
    input.disabled = true;
    try {
      const data = new FormData();
      data.append("file", file);
      const importer = input.dataset.upload === "registry"
        ? (/\.(db|sqlite|sqlite3)$/i.test(file.name) ? "ru-software-sqlite" : "ru-software")
        : "bundle";
      const report = await SZI.request(`/api/admin/import/${importer}`, { method: "POST", body: data });
      status.textContent = `Загружено: ${report.imported}. Ошибок: ${report.errors.length}. ` + report.errors.slice(0, 3).join("; ");
      if (input.dataset.upload === "registry") await loadRegistry();
      if (input.dataset.upload === "tools") await loadTools();
      if (input.dataset.upload === "org") await loadOrg();
      if (input.dataset.upload === "requirements") await loadRequirements();
    } catch (err) {
      status.textContent = err.message;
    } finally {
      input.disabled = false;
      input.value = "";
    }
  });
});

document.getElementById("logout").addEventListener("click", async () => {
  await SZI.logout();
  window.location.replace("/");
});

document.getElementById("export-btn").addEventListener("click", async () => {
  const preview = document.getElementById("export-preview");
  try {
    const data = await SZI.request("/api/admin/export");
    const text = JSON.stringify(data, null, 2);
    preview.textContent = text;
    preview.classList.remove("hidden");
    const blob = new Blob([text], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "szi-bundle.json";
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    preview.classList.remove("hidden");
    preview.textContent = err.message;
  }
});

document.getElementById("add-requirements").addEventListener("click", () => requirementsUi.openForm());
document.getElementById("add-tools").addEventListener("click", () => toolsUi.openForm({ kind: "tool" }));
document.getElementById("add-org").addEventListener("click", () => orgUi.openForm({ kind: "org" }));

let registryOffset = 0;
let registryQuery = "";
let priceTimer;
let registryState = "active";
let registrySort = "reg_number";
let registryDirection = "asc";
let registryRequest = 0;

function registryParams() {
  return new URLSearchParams({q: registryQuery, state: registryState,
    sort: registrySort, direction: registryDirection});
}

function sourceLink(url, label) {
  try {
    const parsed = new URL(url);
    if (!["https:", "http:"].includes(parsed.protocol)) return "—";
    return `<a href="${esc(parsed.href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
  } catch { return "—"; }
}

async function loadRegistry() {
  const root = document.getElementById("registry-table");
  const request = ++registryRequest;
  try {
    const params = registryParams();
    params.set("offset", registryOffset);
    params.set("limit", 50);
    root.setAttribute("aria-busy", "true");
    const data = await SZI.request(`/api/admin/registry?${params}`);
    if (request !== registryRequest) return;
    const columns = [["reg_number", "Номер"], ["name", "ПО"], ["owner", "Правообладатель"],
      ["status", "Статус"], ["value", "Стоимость, руб."], ["source", "Источник"]];
    const headers = columns.map(([key, title]) => `<button type="button" class="sort-column" data-sort="${key}"
      aria-label="Сортировать: ${title}" title="Сортировка по возрастанию / убыванию">${title} ${registrySort === key ? (registryDirection === "asc" ? "↑" : "↓") : "↕"}</button>`);
    root.innerHTML = table(headers,
      data.items.map(({ record: r, price: p, source_url: url }) => `<tr>
        <td>${esc(r.reg_number)}</td><td>${esc(r.name)}</td><td>${esc(r.owner)}</td>
        <td>${r.exclusion_date ? `Исключено: ${esc(r.exclusion_date)}` : "В реестре"}</td>
        <td>${p && ["ok", "free"].includes(p.status) && p.value != null ? esc(p.value.toLocaleString("ru-RU")) : "-"}</td>
        <td>${sourceLink(url, "Источник")}</td></tr>`));
    root.removeAttribute("aria-busy");
    document.getElementById("registry-count").textContent = data.total ? `${registryOffset + 1}–${Math.min(registryOffset + 50, data.total)} из ${data.total}` : "Реестр пока пуст";
    document.getElementById("registry-prev").disabled = registryOffset === 0;
    document.getElementById("registry-next").disabled = registryOffset + 50 >= data.total;
    document.getElementById("registry-excel").href = `/api/admin/registry/export.xlsx?${registryParams()}`;
  } catch (err) { renderError(root, err); }
}

document.getElementById("registry-table").addEventListener("click", event => {
  const button = event.target.closest("[data-sort]");
  if (!button) return;
  registryDirection = registrySort === button.dataset.sort && registryDirection === "asc" ? "desc" : "asc";
  registrySort = button.dataset.sort;
  registryOffset = 0;
  loadRegistry();
});
document.querySelectorAll("[data-registry-state]").forEach(button => {
  button.addEventListener("click", () => {
    registryState = button.dataset.registryState;
    registryOffset = 0;
    document.querySelectorAll("[data-registry-state]").forEach(b => {
      b.classList.toggle("secondary", b !== button);
      b.setAttribute("aria-pressed", String(b === button));
    });
    loadRegistry();
  });
});
document.querySelectorAll("[data-official-format]").forEach(control => control.addEventListener("click", async event => {
  const button = event.currentTarget;
  const status = document.getElementById("registry-download-status");
  const format = button.dataset.officialFormat;
  button.disabled = true;
  status.textContent = `Скачивание ${format.toUpperCase()} с сайта реестра…`;
  try {
    const response = await fetch(`/api/admin/registry/download/${format}`, { credentials: "same-origin" });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Не удалось скачать выгрузку");
    }
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement("a");
    a.href = url; a.download = `registry.${format}`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status.textContent = `${format.toUpperCase()} скачан.`;
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
}));

document.getElementById("registry-search").addEventListener("submit", event => {
  event.preventDefault();
  registryQuery = document.getElementById("registry-query").value.trim();
  registryOffset = 0;
  loadRegistry();
});
document.getElementById("registry-prev").addEventListener("click", () => { registryOffset = Math.max(0, registryOffset - 50); loadRegistry(); });
document.getElementById("registry-next").addEventListener("click", () => { registryOffset += 50; loadRegistry(); });

async function pollPrices() {
  clearTimeout(priceTimer);
  try {
    const job = await SZI.request("/api/admin/registry/prices/status");
    const running = job.status === "running";
    document.getElementById("collect-prices").disabled = running;
    document.getElementById("retry-prices").disabled = running;
    document.getElementById("refresh-prices").disabled = running;
    document.getElementById("price-progress").textContent = job.status === "idle" ? "" :
      `${running ? "Обработка" : job.status === "failed" ? "Сбой" : "Завершено"}: ${job.done}/${job.total}, ошибок: ${job.errors}. ${job.message || ""}`;
    if (running) priceTimer = setTimeout(pollPrices, 2000);
    else if (job.status !== "idle") await loadRegistry();
  } catch (err) { document.getElementById("price-progress").textContent = err.message; }
}

async function startPrices(retry, refresh = false) {
  document.getElementById("collect-prices").disabled = true;
  document.getElementById("retry-prices").disabled = true;
  document.getElementById("refresh-prices").disabled = true;
  try {
    await SZI.request(`/api/admin/registry/prices?retry=${retry}&refresh=${refresh}`, { method: "POST" });
  } catch (err) { showFlash(document.getElementById("page-registry"), err.message); }
  await pollPrices();
}
document.getElementById("collect-prices").addEventListener("click", () => startPrices(false));
document.getElementById("retry-prices").addEventListener("click", () => startPrices(true));
document.getElementById("refresh-prices").addEventListener("click", () => startPrices(false, true));

(async () => {
  const user = await SZI.requireAdmin();
  if (!user) return;
  document.getElementById("who").textContent = `${user.login} · администратор`;
  showPage("dashboard");
})();
