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

let activePage;
let registryVisit = 0;
let showPriceResult = false;

function showPage(id) {
  if (activePage === "tools" && id !== "tools") {
    registryVisit++;
    showPriceResult = false;
    clearTimeout(priceTimer);
    const registryPage = document.getElementById("page-tools");
    registryPage.querySelector(".flash")?.remove();
    document.getElementById("registry-download-fallback").hidden = true;
    registryPage.querySelectorAll('[role="status"]:not(#registry-count)').forEach((status) => {
      status.textContent = "";
    });
  }
  activePage = id;
  pages.forEach((page) => page.classList.toggle("hidden", page.id !== `page-${id}`));
  navButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.page === id));
  if (id === "dashboard") loadDashboard();
  if (id === "requirements") loadRequirements();
  if (id === "org") loadOrg();
  if (id === "gaps") loadGaps();
  if (id === "tools") {
    loadRegistry();
    if (toolsView === "downloads") {
      loadRegistryImportDate();
      pollPrices();
    }
  }
  if (id === "profile") loadAdminProfile();
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

const catalogDeleteDialog = document.getElementById("catalog-delete-dialog");

function confirmCatalogDelete(id) {
  if (catalogDeleteDialog.open) return Promise.resolve(false);
  document.getElementById("catalog-delete-name").textContent = id;
  catalogDeleteDialog.returnValue = "";
  return new Promise(resolve => {
    catalogDeleteDialog.addEventListener("close", () => {
      resolve(catalogDeleteDialog.returnValue === "delete");
    }, {once: true});
    catalogDeleteDialog.showModal();
  });
}

function bindCrud({ tableId, formId, listPath, itemPath, columns = [], fields = [], formHtml, toPayload, toRow, filter, refreshTable }) {
  const tableRoot = document.getElementById(tableId);
  const formRoot = document.getElementById(formId);
  let cached = [];
  let offset = 0;
  let query = "";
  let sortIndex = 0;
  let sortAscending = true;
  const collator = new Intl.Collator("ru", {numeric: true});

  async function refresh(reload = true) {
    if (refreshTable) return refreshTable();
    try {
      if (reload) cached = await loadList(listPath);
      let items = filter ? cached.filter(filter) : cached;
      if (query) items = items.filter(item =>
        [item.id, item.name, item.title, item.vendor].join(" ").toLocaleLowerCase().includes(query.toLocaleLowerCase()));
      const field = fields[sortIndex];
      if (field) items = [...items].sort((a, b) =>
        (sortAscending ? 1 : -1) * collator.compare(String(a[field] ?? ""), String(b[field] ?? "")));
      const headers = columns.map((label, index) => label
        ? `<button class="sort-column" type="button" data-catalog-sort="${index}">${label} ${index === sortIndex ? (sortAscending ? "↑" : "↓") : "↕"}</button>`
        : "");
      if (offset >= items.length) offset = Math.max(0, Math.floor((items.length - 1) / 50) * 50);
      tableRoot.innerHTML = `<form data-catalog-search class="card toolbar">
          <label for="${tableId}-query">Поиск по коду или названию</label>
          <input id="${tableId}-query" name="q" type="search" value="${esc(query)}">
          <button class="btn secondary" type="submit">Найти</button></form><div class="catalog-table-scroll">` + table(
        headers, items.slice(offset, offset + 50).map((item) => toRow(item)),
      ) + `</div><div class="toolbar pagination"><button class="btn secondary" data-prev ${offset === 0 ? "disabled" : ""}>Назад</button>
        <span>${items.length ? `${offset + 1}–${Math.min(offset + 50, items.length)} из ${items.length}` : "Нет записей"}</span>
        <button class="btn secondary" data-next ${offset + 50 >= items.length ? "disabled" : ""}>Далее</button></div>`;
    } catch (err) {
      renderError(tableRoot, err);
    }
  }

  function openForm(values = {}) {
    formRoot.classList.remove("hidden");
    formRoot.innerHTML = formHtml(values);
    formRoot.scrollIntoView({block: "nearest"});
    formRoot.querySelector("input:not([type=hidden]):not([readonly])")?.focus({preventScroll: true});
    formRoot.querySelector("form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = event.submitter;
      if (submit) submit.disabled = true;
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
      } finally {
        if (submit) submit.disabled = false;
      }
    });
    formRoot.querySelector("[data-cancel]").addEventListener("click", () => {
      formRoot.classList.add("hidden");
    });
  }

  tableRoot.addEventListener("click", async (event) => {
    const btn = event.target.closest("button");
    if (!btn) return;
    if (btn.hasAttribute("data-catalog-sort")) {
      const index = Number(btn.dataset.catalogSort);
      sortAscending = index !== sortIndex || !sortAscending;
      sortIndex = index;
      offset = 0;
      await refresh(false);
      return;
    }
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
      if (!await confirmCatalogDelete(id)) return;
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
  fields: ["id", "group", "title", "source"],
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
        <input type="hidden" name="covers" value="${esc((v.covers || []).join(", "))}">
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
      <td class="row-actions">${itemActions(item, orgView === "coverage")}</td></tr>`;
}

function itemActions(item, coverageView) {
  if (coverageView) return `<button class="btn secondary" type="button" data-item-coverage="${esc(item.id)}"
    data-item-name="${esc(item.name)}">Изменить требования</button>`;
  return `<button class="btn secondary" data-edit data-id="${esc(item.id)}">Изменить</button>
    <button class="btn danger" data-delete data-id="${esc(item.id)}">Удалить</button>`;
}

const toolsUi = bindCrud({
  tableId: "registry-table",
  formId: "tool-form",
  itemPath: (id) => `/api/admin/items/${encodeURIComponent(id)}`,
  formHtml: itemFormHtml,
  toPayload: itemPayload,
  refreshTable: loadRegistry,
});

const orgUi = bindCrud({
  tableId: "org-table",
  formId: "org-form",
  listPath: "/api/items",
  itemPath: (id) => `/api/admin/items/${encodeURIComponent(id)}`,
  columns: ["Код", "Название", "Закрывает", ""],
  fields: ["id", "name", "covers"],
  filter: (item) => item.kind === "org",
  formHtml: itemFormHtml,
  toPayload: itemPayload,
  toRow: itemRow,
});

async function loadRequirements() {
  await requirementsUi.refresh();
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

document.getElementById("add-requirements").addEventListener("click", () => requirementsUi.openForm());
document.getElementById("add-tools").addEventListener("click", () => toolsUi.openForm({kind: "tool"}));
document.getElementById("add-org").addEventListener("click", () => orgUi.openForm({kind: "org"}));

document.querySelectorAll("[data-upload]").forEach((input) => {
  input.addEventListener("change", async () => {
    const status = document.querySelector(`[data-upload-status="${input.dataset.upload}"]`);
    const file = input.files && input.files[0];
    const visit = registryVisit;
    const showStatus = () => input.dataset.upload !== "registry" || visit === registryVisit;
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
      if (showStatus()) {
        status.textContent = `Загружено: ${report.imported}. Ошибок: ${report.errors.length}.`;
        if (report.errors.length) status.textContent += " " + report.errors.slice(0, 3).join("; ");
      }
      if (input.dataset.upload === "registry") {
        registryOffset = 0;
        await Promise.all([loadRegistry(), loadRegistryImportDate()]);
      }
      if (input.dataset.upload === "org") await loadOrg();
      if (input.dataset.upload === "requirements") await loadRequirements();
    } catch (err) {
      if (showStatus()) status.textContent = err.message;
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

let registryOffset = 0;
let registryQuery = "";
let priceTimer;
let registryState = "active";
let registrySort = "name";
let registryDirection = "asc";
let registryRequest = 0;
let toolsView = "downloads";
let orgView = "downloads";

function bindCatalogTabs(pageId, onChange) {
  const page = document.getElementById(pageId);
  const buttons = [...page.querySelectorAll("[data-catalog-view]")];
  const panels = [...page.querySelectorAll("[data-view-panel]")];
  buttons.forEach(button => button.addEventListener("click", () => {
    if (button.getAttribute("aria-pressed") === "true") return;
    const view = button.dataset.catalogView;
    buttons.forEach(tab => {
      tab.classList.toggle("secondary", tab !== button);
      tab.setAttribute("aria-pressed", String(tab === button));
    });
    panels.forEach(panel => panel.hidden = panel.dataset.viewPanel !== view);
    onChange(view);
  }));
}

bindCatalogTabs("page-tools", view => {
  toolsView = view;
  const downloads = toolsView === "downloads";
  if (!downloads && registrySort === "value") {
    registrySort = "name";
    registryDirection = "asc";
    registryOffset = 0;
  }
  clearTimeout(priceTimer);
  if (downloads) {
    loadRegistryImportDate();
    pollPrices();
  }
  document.getElementById("registry-table").replaceChildren();
  loadRegistry();
});
bindCatalogTabs("page-org", view => {
  orgView = view;
  orgUi.refresh(false);
});

function registryParams() {
  return new URLSearchParams({q: registryQuery, state: registryState,
    sort: registrySort, direction: registryDirection});
}

async function loadRegistryImportDate() {
  const target = document.getElementById("registry-import-date");
  try {
    const {last_import_at: imported, source_date: source} = await SZI.request("/api/admin/registry/import-status");
    const format = new Intl.DateTimeFormat("ru-RU");
    if (source) {
      target.textContent = `Актуальность реестра на: ${format.format(new Date(`${source}T00:00:00`))}`;
    } else if (imported) {
      target.textContent = `Дата выгрузки неизвестна. Последний импорт: ${format.format(new Date(imported))}`;
    } else {
      target.textContent = "Актуальность реестра: дата неизвестна";
    }
  } catch {
    target.textContent = "Не удалось загрузить дату актуальности реестра";
  }
}

function sourceLink(url, label) {
  try {
    const parsed = new URL(url);
    if (!["https:", "http:"].includes(parsed.protocol)) return esc(label);
    return `<a href="${esc(parsed.href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
  } catch { return esc(label); }
}

async function loadRegistry() {
  const root = document.getElementById("registry-table");
  const request = ++registryRequest;
  try {
    const params = registryParams();
    params.set("offset", registryOffset);
    params.set("limit", 50);
    if (!root.innerHTML) root.textContent = "Загрузка средств…";
    root.setAttribute("aria-busy", "true");
    const data = await SZI.request(`/api/admin/tools?${params}`);
    if (request !== registryRequest) return;
    if (registryOffset && registryOffset >= data.total) {
      registryOffset = Math.max(0, Math.floor((data.total - 1) / 50) * 50);
      return loadRegistry();
    }
    const downloads = toolsView === "downloads";
    const columns = [["name", "Название"], ["covers", "Закрывает"], ["owner", "Правообладатель"]];
    if (downloads) columns.push(["value", "Стоимость, руб."]);
    const headers = columns.map(([key, title]) => `<button type="button" class="sort-column" data-sort="${key}"
      aria-label="Сортировать: ${title}" title="Сортировка по возрастанию / убыванию">${title} ${registrySort === key ? (registryDirection === "asc" ? "↑" : "↓") : "↕"}</button>`);
    root.innerHTML = table([...headers, ""],
      data.items.map(({ item, record: r, price: p, manual_price: manual, source_url: url }) => `<tr>
        <td>${sourceLink(url, item.name)}</td><td>${esc(item.covers.join(", "))}</td><td>${esc(item.vendor)}</td>
        ${downloads ? `<td>${p && ["ok", "free"].includes(p.status) && p.value != null ? esc(p.value.toLocaleString("ru-RU")) : "—"}
          ${r ? `<button class="registry-edit-price" type="button" title="Изменить цену" data-price-number="${r.reg_number}"
            data-price-value="${esc(manual ?? p?.value ?? "")}" aria-label="Редактировать цену: ${esc(item.name)}"><span aria-hidden="true">✎</span></button>` : ""}</td>` : ""}
        <td class="row-actions">${itemActions(item, !downloads)}</td></tr>`));
    document.getElementById("registry-count").textContent = data.total ? `${registryOffset + 1}–${Math.min(registryOffset + 50, data.total)} из ${data.total}` : "Реестр пока пуст";
    document.getElementById("registry-prev").disabled = registryOffset === 0;
    document.getElementById("registry-next").disabled = registryOffset + 50 >= data.total;
  } catch (err) {
    if (request === registryRequest) renderError(root, err);
  } finally {
    if (request === registryRequest) root.removeAttribute("aria-busy");
  }
}

const itemCoverageDialog = document.getElementById("item-coverage-dialog");
const itemCoverageForm = document.getElementById("item-coverage-form");
const itemCoverageQuery = document.getElementById("item-coverage-query");
const itemCoverageCount = document.getElementById("item-coverage-count");
const itemCoverageOptions = document.getElementById("item-coverage-options");
const itemCoverageSuggestions = document.getElementById("item-coverage-suggestions");
const itemCoverageError = document.getElementById("item-coverage-error");
const itemCoverageSave = itemCoverageForm.querySelector('button[type="submit"]');
let itemCoverageItem;
let itemCoverageRequirements;
let selectedRequirements;
let itemCoverageBusy = false;

function requirementOption({id, title, reason}) {
  return `<label class="item-coverage-option">
    <input type="checkbox" value="${esc(id)}" ${selectedRequirements.has(id) ? "checked" : ""}>
    <span><strong>${esc(id)}</strong> ${esc(title)}
      ${reason ? `<span class="item-coverage-reason">${esc(reason)}</span>` : ""}</span>
  </label>`;
}

function renderItemCoverage() {
  const query = itemCoverageQuery.value.trim().toLocaleLowerCase("ru");
  const matches = itemCoverageRequirements.filter(({ id, title }) =>
    `${id} ${title}`.toLocaleLowerCase("ru").includes(query));
  itemCoverageCount.textContent = `Выбрано: ${selectedRequirements.size}`;
  itemCoverageOptions.innerHTML = matches.length ? matches.map(requirementOption).join("") : "Требования не найдены.";
}

document.querySelector("main").addEventListener("click", async event => {
  const button = event.target.closest("[data-item-coverage]");
  if (!button || itemCoverageBusy) return;
  itemCoverageBusy = true;
  itemCoverageItem = null;
  itemCoverageQuery.disabled = itemCoverageSave.disabled = true;
  itemCoverageQuery.value = "";
  itemCoverageCount.textContent = "";
  itemCoverageError.textContent = "";
  itemCoverageSuggestions.hidden = true;
  itemCoverageSuggestions.replaceChildren();
  document.getElementById("item-coverage-name").textContent = button.dataset.itemName;
  itemCoverageOptions.textContent = "Загрузка требований…";
  itemCoverageDialog.showModal();
  try {
    const id = encodeURIComponent(button.dataset.itemCoverage);
    const {item, requirements, suggestions, docs_url: docs} = await SZI.request(
      `/api/admin/items/${id}/coverage/suggestions`,
    );
    if (!itemCoverageDialog.open) return;
    itemCoverageItem = item;
    selectedRequirements = new Set(item.covers);
    const known = new Set(requirements.map(req => req.id));
    itemCoverageRequirements = [...requirements, ...[...selectedRequirements]
      .filter(id => !known.has(id)).map(id => ({ id, title: "Нет в справочнике" }))]
      .sort((a, b) => Number(selectedRequirements.has(b.id)) - Number(selectedRequirements.has(a.id)));
    itemCoverageSuggestions.innerHTML = `<h3>Предложения к проверке</h3>
      ${suggestions.length ? suggestions.map(requirementOption).join("") : "<p>Для этой позиции нет новых предложений.</p>"}
      ${docs ? sourceLink(docs, "Документация") : ""}`;
    itemCoverageSuggestions.hidden = false;
    renderItemCoverage();
    itemCoverageQuery.disabled = itemCoverageSave.disabled = false;
    itemCoverageQuery.focus();
  } catch (err) {
    itemCoverageOptions.textContent = "";
    itemCoverageError.textContent = err.message;
  } finally {
    itemCoverageBusy = false;
  }
});
itemCoverageQuery.addEventListener("input", renderItemCoverage);
itemCoverageForm.addEventListener("change", event => {
  const checkbox = event.target;
  if (!checkbox.matches('input[type="checkbox"]')) return;
  if (checkbox.checked) selectedRequirements.add(checkbox.value);
  else selectedRequirements.delete(checkbox.value);
  for (const option of itemCoverageForm.querySelectorAll('input[type="checkbox"]')) {
    if (option.value === checkbox.value) option.checked = checkbox.checked;
  }
  itemCoverageCount.textContent = `Выбрано: ${selectedRequirements.size}`;
});
itemCoverageForm.addEventListener("submit", async event => {
  if (event.submitter?.formMethod === "dialog") return;
  event.preventDefault();
  if (!itemCoverageItem || itemCoverageBusy) return;
  itemCoverageBusy = true;
  const cancel = itemCoverageForm.querySelector('[formmethod="dialog"]');
  itemCoverageSave.disabled = cancel.disabled = itemCoverageQuery.disabled = true;
  itemCoverageOptions.inert = true;
  itemCoverageSuggestions.inert = true;
  itemCoverageError.textContent = "";
  try {
    await SZI.request(`/api/admin/items/${encodeURIComponent(itemCoverageItem.id)}/coverage`, {
      method: "PATCH",
      body: JSON.stringify({ expected: itemCoverageItem.covers, covers: [...selectedRequirements] }),
    });
    itemCoverageDialog.close();
    if (itemCoverageItem.kind === "org") await loadOrg();
    else await loadRegistry();
  } catch (err) {
    itemCoverageError.textContent = err.message;
  } finally {
    itemCoverageBusy = false;
    itemCoverageSave.disabled = cancel.disabled = itemCoverageQuery.disabled = false;
    itemCoverageOptions.inert = false;
    itemCoverageSuggestions.inert = false;
  }
});
itemCoverageDialog.addEventListener("cancel", event => {
  if (itemCoverageOptions.inert) event.preventDefault();
});

const priceDialog = document.getElementById("registry-price-dialog");
const priceForm = document.getElementById("registry-price-form");
const priceValue = document.getElementById("registry-price-value");
const priceError = document.getElementById("registry-price-error");

priceForm.addEventListener("submit", async event => {
  if (event.submitter?.formMethod === "dialog") return;
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  priceError.textContent = "";
  try {
    await SZI.request(`/api/admin/registry/${priceForm.dataset.number}/price`, {
      method: "PUT",
      body: JSON.stringify({value: priceValue.value === "" ? null : priceValue.valueAsNumber}),
    });
    priceDialog.close();
    await loadRegistry();
  } catch (error) {
    priceError.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

document.getElementById("registry-table").addEventListener("click", event => {
  const editPrice = event.target.closest("[data-price-number]");
  if (editPrice) {
    priceForm.dataset.number = editPrice.dataset.priceNumber;
    priceValue.value = editPrice.dataset.priceValue;
    priceError.textContent = "";
    priceDialog.showModal();
    return;
  }
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
const downloadDialog = document.getElementById("registry-download-dialog");
document.getElementById("registry-download").addEventListener("click", () => downloadDialog.showModal());
const registryExportButtons = document.querySelectorAll("[data-registry-export]");
registryExportButtons.forEach(control => control.addEventListener("click", async event => {
  const status = document.getElementById("registry-download-status");
  const fallback = document.getElementById("registry-download-fallback");
  const format = event.currentTarget.dataset.registryExport;
  const visit = registryVisit;
  registryExportButtons.forEach(button => button.disabled = true);
  downloadDialog.close();
  fallback.hidden = true;
  status.textContent = `Скачивание ${format.toUpperCase()} с сайта реестра…`;
  try {
    const result = await SZI.request(`/api/admin/registry/download/${format}`, {method: "POST"});
    if (visit !== registryVisit) return;
    fallback.hidden = !result.cached;
    status.textContent = result.cached
      ? `Свежая выгрузка недоступна. Последняя сохранённая копия: ${result.path}`
      : `Файл сохранён: ${result.path}`;
  } catch (error) {
    if (visit === registryVisit) {
      status.textContent = error.message;
      fallback.hidden = false;
    }
  }
  finally { registryExportButtons.forEach(button => button.disabled = false); }
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
  if (activePage !== "tools" || toolsView !== "downloads") return;
  const visit = registryVisit;
  clearTimeout(priceTimer);
  try {
    const job = await SZI.request("/api/admin/registry/prices/status");
    if (visit !== registryVisit || toolsView !== "downloads") return;
    const running = ["running", "stopping"].includes(job.status);
    if (running) showPriceResult = true;
    const collectButton = document.getElementById("collect-prices");
    const stopButton = document.getElementById("stop-prices");
    if (collectButton) collectButton.disabled = running;
    if (stopButton) stopButton.disabled = job.status !== "running";
    const counts = `${job.done.toLocaleString("ru-RU")} из ${job.total.toLocaleString("ru-RU")}`;
    document.getElementById("price-progress").textContent = job.status === "idle" || !showPriceResult ? "" :
      `${({running: "Обработка", stopping: "Остановка", stopped: "Остановлено", failed: "Сбой", completed: "Завершено"})[job.status]}: ${counts} уникальных ссылок на цены. Ошибок: ${job.errors}. ${job.message || ""}`;
    if (running) priceTimer = setTimeout(pollPrices, 2000);
    else if (job.status !== "idle" && showPriceResult) await loadRegistry();
  } catch (err) {
    if (visit === registryVisit) document.getElementById("price-progress").textContent = err.message;
  }
}

document.getElementById("collect-prices").addEventListener("click", async event => {
  const visit = registryVisit;
  showPriceResult = true;
  event.currentTarget.disabled = true;
  try {
    await SZI.request("/api/admin/registry/prices", {method: "POST"});
  } catch (error) {
    if (visit === registryVisit) showFlash(document.getElementById("page-tools"), error.message);
  }
  if (activePage === "tools") await pollPrices();
});
document.getElementById("stop-prices")?.addEventListener("click", async event => {
  const visit = registryVisit;
  showPriceResult = true;
  event.currentTarget.disabled = true;
  try {
    await SZI.request("/api/admin/registry/prices/stop", {method: "POST"});
  } catch (error) {
    if (visit === registryVisit) showFlash(document.getElementById("page-tools"), error.message);
  }
  if (activePage === "tools") await pollPrices();
});

const adminProfileForm = document.getElementById("admin-profile-form");

async function loadAdminProfile() {
  try {
    const [user, users] = await Promise.all([SZI.me(), SZI.request("/api/admin/users")]);
    adminProfileForm.elements.login.value = user.login;
    document.getElementById("admin-users").innerHTML = table(
      ["Логин", "Роль", ""],
      users.map(entry => `<tr><td>${esc(entry.login)}</td><td>${entry.role === "admin" ? "Администратор" : "Пользователь"}</td>
        <td class="row-actions">${entry.id === user.id ? "" : `<button class="btn secondary" type="button"
          data-user-id="${entry.id}" data-user-role="${esc(entry.role)}"
          data-user-login="${esc(entry.login)}">Изменить</button>
          <button class="btn danger" type="button" data-delete-user="${entry.id}"
            data-user-login="${esc(entry.login)}">Удалить</button>`}</td></tr>`),
    );
  } catch (error) {
    showFlash(document.getElementById("page-profile"), error.message);
  }
}

document.getElementById("admin-profile").addEventListener("click", () => showPage("profile"));
adminProfileForm.addEventListener("submit", async event => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(adminProfileForm));
  values.login = values.login.trim();
  values.new_password ||= null;
  const button = event.submitter;
  button.disabled = true;
  try {
    await SZI.request("/api/admin/profile", {method: "PUT", body: JSON.stringify(values)});
    adminProfileForm.reset();
    if (values.new_password) {
      window.location.assign("/");
      return;
    }
    await loadAdminProfile();
    showFlash(document.getElementById("page-profile"), "Профиль сохранён.", true);
  } catch (error) {
    showFlash(document.getElementById("page-profile"), error.message);
  } finally {
    adminProfileForm.elements.current_password.value = "";
    button.disabled = false;
  }
});

const adminUserDialog = document.getElementById("admin-user-dialog");
const adminUserForm = document.getElementById("admin-user-form");
const adminUserError = document.getElementById("admin-user-error");
const adminUserDeleteDialog = document.getElementById("admin-user-delete-dialog");
const adminUserDeleteForm = document.getElementById("admin-user-delete-form");
const adminUserDeleteError = document.getElementById("admin-user-delete-error");

document.getElementById("admin-users").addEventListener("click", event => {
  const button = event.target.closest("[data-delete-user]");
  if (!button) return;
  adminUserDeleteForm.reset();
  adminUserDeleteForm.dataset.userId = button.dataset.deleteUser;
  document.getElementById("admin-user-delete-login").textContent = button.dataset.userLogin;
  adminUserDeleteError.textContent = "";
  adminUserDeleteDialog.showModal();
});
adminUserDeleteDialog.addEventListener("close", () => adminUserDeleteForm.reset());
adminUserDeleteDialog.addEventListener("cancel", event => {
  if (adminUserDeleteForm.inert) event.preventDefault();
});
adminUserDeleteForm.addEventListener("submit", async event => {
  if (event.submitter?.formMethod === "dialog") return;
  event.preventDefault();
  if (adminUserDeleteForm.inert) return;
  const body = JSON.stringify(Object.fromEntries(new FormData(adminUserDeleteForm)));
  adminUserDeleteForm.inert = true;
  adminUserDeleteError.textContent = "";
  try {
    await SZI.request(`/api/admin/users/${adminUserDeleteForm.dataset.userId}`, {method: "DELETE", body});
    adminUserDeleteDialog.close();
    await loadAdminProfile();
    showFlash(document.getElementById("page-profile"), "Пользователь удалён.", true);
  } catch (error) {
    adminUserDeleteError.textContent = error.message;
  } finally {
    adminUserDeleteForm.inert = false;
    adminUserDeleteForm.elements.current_password.value = "";
  }
});

document.getElementById("admin-users").addEventListener("click", event => {
  const button = event.target.closest("[data-user-id]");
  if (!button) return;
  adminUserForm.reset();
  adminUserForm.dataset.userId = button.dataset.userId;
  adminUserForm.elements.role.value = button.dataset.userRole;
  document.getElementById("admin-user-title").textContent = `Настройки: ${button.dataset.userLogin}`;
  adminUserError.textContent = "";
  adminUserDialog.showModal();
});
adminUserDialog.addEventListener("close", () => adminUserForm.reset());
adminUserForm.addEventListener("submit", async event => {
  if (event.submitter?.formMethod === "dialog") return;
  event.preventDefault();
  const button = event.submitter;
  const values = Object.fromEntries(new FormData(adminUserForm));
  values.new_password ||= null;
  button.disabled = true;
  adminUserError.textContent = "";
  try {
    await SZI.request(`/api/admin/users/${adminUserForm.dataset.userId}`, {
      method: "PUT",
      body: JSON.stringify(values),
    });
    adminUserDialog.close();
    await loadAdminProfile();
    showFlash(document.getElementById("page-profile"), "Настройки пользователя сохранены.", true);
  } catch (error) {
    adminUserError.textContent = error.message;
  } finally {
    adminUserForm.elements.current_password.value = "";
    button.disabled = false;
  }
});

const coverageDialog = document.getElementById("coverage-dialog");
const coverageForm = document.getElementById("coverage-form");
const coverageFile = document.getElementById("coverage-file");
const coverageReport = document.getElementById("coverage-report");
const coverageErrors = document.getElementById("coverage-errors");
const coveragePreview = coverageForm.querySelector('[value="preview"]');
const coverageApply = coverageForm.querySelector('[value="apply"]');
let coverageBusy = false;

function clearCoverageReport() {
  coverageReport.textContent = "";
  coverageErrors.replaceChildren();
  coverageErrors.hidden = true;
  coverageApply.disabled = true;
}

document.querySelectorAll("[data-coverage-kind]").forEach(button => {
  button.addEventListener("click", () => {
    if (coverageBusy) return;
    coverageForm.reset();
    clearCoverageReport();
    coverageForm.dataset.kind = button.dataset.coverageKind;
    coverageDialog.showModal();
  });
});
coverageFile.addEventListener("change", clearCoverageReport);
coverageForm.addEventListener("submit", async event => {
  if (event.submitter?.formMethod === "dialog") return;
  event.preventDefault();
  if (coverageBusy) return;
  const apply = event.submitter?.value === "apply";
  if (apply && coverageApply.disabled) return;
  const kind = coverageForm.dataset.kind;
  const body = new FormData(coverageForm);
  clearCoverageReport();
  coverageBusy = true;
  coveragePreview.disabled = true;
  coverageFile.disabled = true;
  coverageReport.textContent = apply ? "Сохраняем связи…" : "Проверяем файл…";
  try {
    const report = await SZI.request(`/api/admin/coverage/import?kind=${kind}&apply=${apply}`, {
      method: "POST", body,
    });
    const label = report.applied ? "Добавлено" : "К добавлению";
    coverageReport.textContent = `${label}: ${report.added}. Повторы: ${report.existing}. ` +
      `Пропущено: ${report.skipped}. Ошибок: ${report.error_count}.`;
    if (report.error_count) {
      coverageReport.append(" Исправьте ошибки в файле и загрузите его заново.");
      coverageErrors.hidden = false;
      for (const error of report.errors) {
        const li = document.createElement("li");
        li.textContent = error;
        coverageErrors.append(li);
      }
    }
    coverageApply.disabled = apply || report.error_count > 0 || report.added === 0;
    if (report.applied) {
      if (kind === "tool") await loadRegistry();
      else await loadOrg();
    }
  } catch (error) {
    coverageReport.textContent = error.message;
  } finally {
    coverageBusy = false;
    coveragePreview.disabled = false;
    coverageFile.disabled = false;
  }
});

(async () => {
  const user = await SZI.requireAdmin();
  if (!user) return;
  showPage("dashboard");
})();
