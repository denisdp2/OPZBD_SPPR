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
}

async function loadList(path) {
  return SZI.request(path);
}

function renderError(target, err) {
  target.innerHTML = `<div class="card">${err.message}</div>`;
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

  async function refresh() {
    try {
      let items = await loadList(listPath);
      if (filter) items = items.filter(filter);
      tableRoot.innerHTML = table(
        columns,
        items.map((item) => toRow(item)),
      );
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
    const id = btn.dataset.id;
    if (btn.dataset.edit) {
      try {
        const item = await SZI.request(itemPath(id));
        openForm(item);
      } catch (err) {
        renderError(tableRoot, err);
      }
    }
    if (btn.dataset.delete) {
      if (!confirm(`Удалить «${id}»?`)) return;
      try {
        await SZI.request(itemPath(id), { method: "DELETE" });
        await refresh();
      } catch (err) {
        renderError(tableRoot, err);
      }
    }
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
        <div><label>Код</label><input name="id" value="${esc(v.id)}" required></div>
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
        <div><label>Код</label><input name="id" value="${esc(v.id)}" required></div>
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
  input.addEventListener("change", () => {
    const status = document.querySelector(`[data-upload-status="${input.dataset.upload}"]`);
    const file = input.files && input.files[0];
    if (!file) {
      status.textContent = "Файл не выбран";
      return;
    }
    status.textContent = `Выбран файл: ${file.name}`;
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

(async () => {
  const user = await SZI.requireAdmin();
  if (!user) return;
  document.getElementById("who").textContent = `${user.login} · администратор`;
  showPage("dashboard");
})();
