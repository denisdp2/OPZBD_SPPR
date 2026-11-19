import { apiRequest } from "../api/http-client.js";
import { workspaceApi } from "../api/workspace-api.js";
import { workspaceService } from "../services/workspace-service.js";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = {
  requirements: [],
  items: [],
  profiles: [],
  optimizers: [],
  selectedRequirements: new Set(),
  candidates: new Map(),
  prices: new Map(),
  profileId: "",
  periodMonths: 12,
  activeKind: "all",
  search: "",
  builderView: "scenario",
  catalogPage: 0,
  selectedPage: 0,
  catalogPageItems: [],
  requirementSearch: "",
  requirementGroup: "all",
  requirementFilter: "all",
  usingExamples: true,
  usingExampleOptimizers: true,
  catalogsEmpty: false,
  serverOnline: false,
  problems: [],
  lastEvaluation: null,
  lastOptimization: null,
  lastPareto: [],
  resultSource: "none",
  isCalculating: false,
  initializedOnce: false,
};

let itemsById = new Map();
let requirementsById = new Map();
let catalogFilter;

const currency = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 });
const number = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const periodNumber = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });

function money(value) {
  return currency.format(Number.isFinite(Number(value)) ? Number(value) : 0);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function profile() {
  return state.profiles.find((entry) => entry.id === state.profileId) ?? state.profiles[0] ?? null;
}

function mandatoryIds() {
  const validIds = new Set(state.requirements.map((entry) => entry.id));
  return (profile()?.mandatory ?? []).filter((id) => validIds.has(id));
}

// Стоимость относится к пользовательскому сценарию, а не к карточке каталога.
// Пустое значение означает, что пользователь ещё не ввёл цену; 0 допустим как цена.
function priceFor(item) {
  return state.prices.get(item.id) ?? { capex: "", opex_month: "" };
}

function requireCandidatePrices() {
  const missing = [...state.candidates.values()].findIndex(({ capex, opex_month }) =>
    capex == null || capex === "" || opex_month == null || opex_month === "");
  if (missing === -1) return true;
  showToast("Заполните стоимость выбранных позиций. Если затрат нет, укажите 0.", "error");
  state.selectedPage = Math.floor(missing / SELECTED_PAGE_SIZE);
  navigateTo("builder");
  showBuilderView("selected");
  return false;
}

function mandatoryRequirementsAreIncluded() {
  const missing = mandatoryIds().filter((id) => !state.selectedRequirements.has(id));
  missing.forEach((id) => state.selectedRequirements.add(id));
}

function candidateCost(candidate, period = state.periodMonths) {
  return Math.max(0, Number(candidate.capex) || 0) + Math.max(0, Number(candidate.opex_month) || 0) * period;
}

function selectedItems() {
  return [...state.candidates.entries()]
    .map(([itemId, costs]) => {
      const item = itemsById.get(itemId);
      return item ? { item, costs, total: candidateCost(costs) } : null;
    })
    .filter(Boolean);
}

function totalSelectedCost() {
  return selectedItems().reduce((total, entry) => total + entry.total, 0);
}

function scenarioFor(itemIds = [...state.candidates.keys()]) {
  return {
    profile_id: state.profileId || null,
    mandatory: null,
    period_months: Math.max(0.1, Math.round((Number(state.periodMonths) || 12) * 10) / 10),
    requirements: [...new Set([...state.selectedRequirements, ...mandatoryIds()])],
    candidates: itemIds.map((itemId) => {
      const costs = state.candidates.get(itemId) ?? priceFor(itemsById.get(itemId) ?? {});
      return { item_id: itemId, capex: Number(costs.capex) || 0, opex_month: Number(costs.opex_month) || 0 };
    }),
  };
}

function localEvaluate(scenario) {
  const requirements = new Set(scenario.requirements);
  const mandatory = mandatoryIds().filter((id) => requirements.has(id));
  const coveredBy = {};
  scenario.candidates.forEach((candidate) => {
    const item = state.items.find((entry) => entry.id === candidate.item_id);
    (item?.covers ?? []).forEach((requirementId) => {
      if (!requirements.has(requirementId)) return;
      coveredBy[requirementId] ??= [];
      coveredBy[requirementId].push(item.id);
    });
  });
  const covered = [...requirements].filter((id) => Boolean(coveredBy[id]?.length));
  const uncovered = [...requirements].filter((id) => !covered.includes(id));
  const uncoveredMandatory = mandatory.filter((id) => !covered.includes(id));
  const totalCost = scenario.candidates.reduce((sum, candidate) => sum + candidateCost(candidate, scenario.period_months), 0);
  return {
    all_mandatory_covered: uncoveredMandatory.length === 0,
    uncovered_mandatory: uncoveredMandatory,
    covered,
    uncovered,
    covered_optional: covered.filter((id) => !mandatory.includes(id)).length,
    total_optional: [...requirements].filter((id) => !mandatory.includes(id)).length,
    total_cost: totalCost,
    covered_by: coveredBy,
  };
}

function candidateSubsets(scenario, maxItems = 16) {
  const candidates = scenario.candidates;
  const count = candidates.length;
  if (count === 0) return [[]];
  if (count <= maxItems) {
    const subsets = [];
    const totalMasks = 1 << count;
    for (let mask = 0; mask < totalMasks; mask += 1) {
      const subset = [];
      for (let bit = 0; bit < count; bit += 1) {
        if (mask & (1 << bit)) subset.push(candidates[bit]);
      }
      subsets.push(subset);
    }
    return subsets;
  }
  // Avoid an exponential browser-side calculation for large catalog selections.
  const byCost = [...candidates].sort((a, b) => candidateCost(a, scenario.period_months) - candidateCost(b, scenario.period_months));
  const byCoverage = [...candidates].sort((a, b) => {
    const itemA = state.items.find((item) => item.id === a.item_id);
    const itemB = state.items.find((item) => item.id === b.item_id);
    const ratioA = (itemA?.covers?.length ?? 0) / Math.max(1, candidateCost(a, scenario.period_months));
    const ratioB = (itemB?.covers?.length ?? 0) / Math.max(1, candidateCost(b, scenario.period_months));
    return ratioB - ratioA;
  });
  const options = [[], ...candidates.map((item) => [item]), [...candidates]];
  for (const ordered of [byCost, byCoverage]) {
    for (let i = 1; i <= ordered.length; i += 1) options.push(ordered.slice(0, i));
  }
  return options;
}

function summarizeSubset(subset, scenario) {
  const subsetScenario = { ...scenario, candidates: subset };
  const evaluation = localEvaluate(subsetScenario);
  return {
    algorithm: "local-example",
    selected: subset.map((item) => item.item_id),
    cost: evaluation.total_cost,
    covered_count: evaluation.covered.length,
    feasible: evaluation.all_mandatory_covered,
    uncovered_mandatory: evaluation.uncovered_mandatory,
    covered: evaluation.covered,
  };
}

function localOptimize(payload) {
  const scenario = payload.scenario;
  const summaries = candidateSubsets(scenario).map((subset) => summarizeSubset(subset, scenario));
  const mandatoryCount = mandatoryIds().length;
  let options = summaries;
  if (payload.mode === "max_coverage") {
    const budget = Math.max(0, Number(payload.budget) || 0);
    options = options.filter((solution) => solution.cost <= budget && solution.feasible);
    options.sort((a, b) => b.covered_count - a.covered_count || a.cost - b.cost);
  } else {
    options = options.filter((solution) => solution.feasible);
    options.sort((a, b) => a.cost - b.cost || b.covered_count - a.covered_count);
  }
  if (options.length) return { ...options[0], algorithm: payload.algorithm, elapsed_ms: null };
  summaries.sort((a, b) => a.uncovered_mandatory.length - b.uncovered_mandatory.length || a.cost - b.cost);
  const leastBad = summaries[0] ?? {
    selected: [], cost: 0, covered_count: 0, feasible: mandatoryCount === 0, uncovered_mandatory: mandatoryIds(),
  };
  return { ...leastBad, algorithm: payload.algorithm, elapsed_ms: null };
}

function localPareto(scenario) {
  const solutions = candidateSubsets(scenario).map((subset) => summarizeSubset(subset, scenario));
  const unique = new Map();
  for (const solution of solutions) {
    const key = `${Math.round(solution.cost)}-${solution.covered_count}-${solution.feasible}`;
    if (!unique.has(key)) unique.set(key, solution);
  }
  const all = [...unique.values()];
  return all.filter((candidate) => !all.some((other) => (
    other.cost <= candidate.cost && other.covered_count >= candidate.covered_count &&
    (other.cost < candidate.cost || other.covered_count > candidate.covered_count) &&
    (!candidate.feasible || other.feasible)
  ))).sort((a, b) => a.cost - b.cost);
}

function showToast(message, type = "info") {
  const region = $("#toast-region");
  if (!region) return;
  const toast = document.createElement("div");
  toast.className = `toast${type === "error" ? " is-error" : type === "success" ? " is-success" : ""}`;
  const mark = document.createElement("span");
  mark.className = "toast-mark";
  mark.textContent = type === "error" ? "!" : type === "success" ? "✓" : "i";
  const copy = document.createElement("span");
  copy.textContent = message;
  toast.append(mark, copy);
  region.append(toast);
  window.setTimeout(() => toast.remove(), 4300);
}

function setLoading(button, loading, idleText) {
  if (!button) return;
  if (loading) {
    button.dataset.idleHtml = button.innerHTML;
    button.disabled = true;
    button.textContent = idleText;
  } else {
    button.disabled = false;
    if (button.dataset.idleHtml) {
      button.innerHTML = button.dataset.idleHtml;
      delete button.dataset.idleHtml;
    }
  }
}

function renderApiState() {
  const notice = $("#data-notice");
  const noticeText = $("#data-notice-text");
  const hasCatalogGap = state.catalogsEmpty;
  if (notice) {
    notice.hidden = !state.usingExamples && !hasCatalogGap;
    if (noticeText) {
      noticeText.textContent = state.usingExamples
        ? "Сервер недоступен. Показаны демонстрационные справочники."
        : "Часть справочников недоступна. Обновите их или обратитесь к администратору.";
    }
  }
}

function renderProfileOptions() {
  const select = $("#profile-select");
  if (!select) return;
  const profiles = [...state.profiles].sort((a, b) => String(a.id).localeCompare(String(b.id), "ru", { numeric: true }));
  select.innerHTML = profiles.map((entry) => (
    `<option value="${escapeHtml(entry.id)}">${escapeHtml(entry.name)}</option>`
  )).join("");
  select.value = state.profileId;
  const description = $("#profile-description");
  if (description) description.textContent = profile()?.description || "Профиль задаёт список обязательных требований.";
}

function renderRequirements() {
  const list = $("#requirements-list");
  if (!list) return;
  const mandatory = new Set(profile()?.mandatory ?? []);
  const groupSelect = $("#requirement-group-filter");
  const groups = [...new Set(state.requirements.map((req) => req.group || "Без группы"))]
    .sort((a, b) => a.localeCompare(b, "ru"));
  if (groupSelect) {
    const selectedGroup = groups.includes(state.requirementGroup) ? state.requirementGroup : "all";
    state.requirementGroup = selectedGroup;
    groupSelect.innerHTML = `<option value="all">Все группы (${state.requirements.length})</option>` + groups.map((group) => {
      const count = state.requirements.filter((req) => (req.group || "Без группы") === group).length;
      return `<option value="${escapeHtml(group)}">${escapeHtml(group)} · ${count}</option>`;
    }).join("");
    groupSelect.value = state.requirementGroup;
  }

  const query = state.requirementSearch.trim().toLocaleLowerCase("ru");
  const visible = state.requirements.filter((req) => {
    const isMandatory = mandatory.has(req.id);
    const group = req.group || "Без группы";
    const scopeMatches = state.requirementFilter === "all" ||
      (state.requirementFilter === "mandatory" && isMandatory) ||
      (state.requirementFilter === "optional" && !isMandatory);
    const groupMatches = state.requirementGroup === "all" || group === state.requirementGroup;
    const searchable = `${req.id} ${req.group ?? ""} ${req.title} ${req.source ?? ""} ${req.description ?? ""}`.toLocaleLowerCase("ru");
    return scopeMatches && groupMatches && (!query || searchable.includes(query));
  });

  const grouped = new Map();
  visible.forEach((req) => {
    const key = req.group || "Без группы";
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(req);
  });
  list.innerHTML = [...grouped.entries()].map(([group, requirements]) => {
    const mandatoryCount = requirements.filter((req) => mandatory.has(req.id)).length;
    const rows = requirements.map((req) => {
      const isMandatory = mandatory.has(req.id);
      const checked = isMandatory || state.selectedRequirements.has(req.id);
      return `<label class="requirement-choice${isMandatory ? " is-mandatory" : ""}">
        <input type="checkbox" data-requirement-id="${escapeHtml(req.id)}" ${checked ? "checked" : ""} ${isMandatory ? "disabled" : ""}>
        <span class="requirement-choice-copy">
          <strong>${escapeHtml(req.title)}${isMandatory ? ' <span class="mandatory-pill">Обязательное</span>' : ""}</strong>
          <small>${escapeHtml(req.id)}${req.source ? ` · ${escapeHtml(req.source)}` : ""}</small>
        </span>
      </label>`;
    }).join("");
    return `<div class="requirement-group"><div class="requirement-group-heading"><strong>${escapeHtml(group)}</strong><span>${requirements.length} · обязательных: ${mandatoryCount}</span></div>${rows}</div>`;
  }).join("") || `<div class="empty-inline">${state.requirements.length ? "По заданным условиям ничего не найдено." : "На сервере нет требований. Проверьте импорт data/seed_bundle.json."}</div>`;

  $("#requirements-selected-count").textContent = String(state.selectedRequirements.size);
  $("#requirements-total-count").textContent = String(state.requirements.length);
  $("#mandatory-in-scenario").textContent = String(mandatoryIds().length);
  $("#excluded-in-scenario").textContent = String(Math.max(0, state.requirements.length - state.selectedRequirements.size));
  $$('[data-requirement-filter]').forEach((button) => {
    button.classList.toggle("is-active", button.dataset.requirementFilter === state.requirementFilter);
  });
  const toggle = $("#toggle-requirements");
  if (toggle) {
    const optionalCount = state.requirements.filter((req) => !mandatory.has(req.id)).length;
    toggle.disabled = optionalCount === 0;
    toggle.textContent = optionalCount === 0
      ? "Все обязательные"
      : state.requirements.every((req) => state.selectedRequirements.has(req.id))
        ? "Снять необязательные" : "Выбрать все";
  }
}

const SELECTED_PAGE_SIZE = 20;

function filterCatalog() {
  const search = state.search.trim().toLocaleLowerCase("ru");
  if (catalogFilter?.search === search && catalogFilter.kind === state.activeKind) {
    return catalogFilter.items;
  }
  const items = state.items.filter((item) => {
    if (state.activeKind !== "all" && item.kind !== state.activeKind) return false;
    if (!search) return true;
    const linked = (item.covers ?? []).map((id) => {
      const requirement = requirementsById.get(id);
      return `${id} ${requirement?.title ?? ""} ${requirement?.group ?? ""}`;
    }).join(" ");
    const registry = item.in_ru_software_registry ? "российское по реестр" : "";
    return [item.name, item.description, item.id, item.vendor, item.fstec_cert_no, linked, registry]
      .join(" ").toLocaleLowerCase("ru").includes(search);
  });
  catalogFilter = { search, kind: state.activeKind, items };
  return items;
}

function renderItem(item, editCosts = false) {
  const selected = state.candidates.has(item.id);
  const costs = state.candidates.get(item.id);
  const covers = (item.covers ?? []).map((id) => {
    const req = requirementsById.get(id);
    const title = req ? `${req.id} · ${req.title}` : `${id} · требование отсутствует в справочнике`;
    return `<span class="cover-chip" title="${escapeHtml(title)}">${escapeHtml(id)}</span>`;
  }).join("");
  const facts = item.kind === "tool" ? `
    <div class="item-facts" aria-label="Сведения о средстве защиты">
      <span class="item-fact ${item.fstec_certified ? "is-positive" : "is-muted"}">${item.fstec_certified ? `Сертификат ФСТЭК${item.fstec_cert_no ? ` · № ${escapeHtml(item.fstec_cert_no)}` : ""}${item.fstec_cert_valid_until ? ` · до ${escapeHtml(item.fstec_cert_valid_until)}` : ""}` : "Без сертификата ФСТЭК"}</span>
      <span class="item-fact ${item.in_ru_software_registry ? "is-positive" : "is-muted"}">${item.in_ru_software_registry ? "В реестре российского ПО" : "Не в реестре российского ПО"}</span>
      ${item.vendor ? `<span class="item-fact">Производитель: ${escapeHtml(item.vendor)}</span>` : ""}
    </div>` : (item.implement_days !== null && item.implement_days !== undefined
      ? `<div class="item-facts"><span class="item-fact">Срок внедрения: ${escapeHtml(item.implement_days)} дн.</span></div>` : "");
  return `<article class="catalog-item${selected ? " is-selected" : ""}">
    <div class="catalog-item-main">
      <div class="catalog-item-title-row"><strong class="catalog-item-title">${escapeHtml(item.name)}</strong><span class="kind-tag${item.kind === "org" ? " kind-org" : ""}">${item.kind === "org" ? "Организационная мера" : "Средство защиты"}</span></div>
      <details class="catalog-details">
        <summary>Сведения</summary>
        ${item.description ? `<p class="catalog-description">${escapeHtml(item.description)}</p>` : ""}
        ${facts}
        <div class="covers-row">${covers || '<span class="cover-chip cover-chip-empty">Нет связанных требований</span>'}</div>
      </details>
      ${editCosts ? `<div class="cost-editor">
        <label>Внедрение, ₽<input type="number" min="0" step="1" placeholder="0" value="${costs.capex === null || costs.capex === undefined ? "" : escapeHtml(costs.capex)}" data-cost-item="${escapeHtml(item.id)}" data-cost-field="capex" aria-label="Стоимость внедрения: ${escapeHtml(item.name)}"></label>
        <label>Эксплуатация в месяц, ₽<input type="number" min="0" step="1" placeholder="0" value="${costs.opex_month === null || costs.opex_month === undefined ? "" : escapeHtml(costs.opex_month)}" data-cost-item="${escapeHtml(item.id)}" data-cost-field="opex_month" aria-label="Стоимость эксплуатации в месяц: ${escapeHtml(item.name)}"></label>
      </div>` : ""}
    </div>
    <button type="button" class="btn ${selected ? "secondary " : ""}compact-button" data-toggle-item="${escapeHtml(item.id)}" aria-label="${selected ? "Убрать из набора" : "Добавить в набор"}: ${escapeHtml(item.name)}" aria-pressed="${selected}">${selected ? "Убрать" : "Добавить"}</button>
  </article>`;
}

function pageItems(items, pageKey, size, controls) {
  const last = Math.max(0, Math.ceil(items.length / size) - 1);
  const page = Math.min(last, Math.max(0, state[pageKey]));
  state[pageKey] = page;
  const start = page * size;
  $(controls.prev).disabled = page === 0;
  $(controls.next).disabled = page === last;
  $(controls.count).textContent = items.length
    ? `${number.format(start + 1)}–${number.format(Math.min(start + size, items.length))} из ${number.format(items.length)}`
    : "Нет позиций";
  return items.slice(start, start + size);
}

function renderCatalog() {
  const visible = pageItems(filterCatalog(), "catalogPage", Number($("#catalog-page-size").value), {
    prev: '[data-catalog-step="-1"]', next: '[data-catalog-step="1"]', count: "#catalog-visible-count",
  });
  state.catalogPageItems = visible;
  $("#catalog-list").innerHTML = visible.map((item) => renderItem(item)).join("") ||
    '<p class="empty-state">По выбранным условиям ничего не найдено.</p>';
  $("#catalog-select-page").disabled = visible.every((item) => state.candidates.has(item.id));
}

function renderSelected() {
  const items = [...state.candidates.keys()].map((id) => itemsById.get(id)).filter(Boolean);
  const visible = pageItems(items, "selectedPage", SELECTED_PAGE_SIZE, {
    prev: '[data-selected-step="-1"]', next: '[data-selected-step="1"]', count: "#selected-visible-count",
  });
  $("#selected-list").innerHTML = visible.map((item) => renderItem(item, true)).join("");
  $("#selected-empty").hidden = items.length > 0;
  $("#selected-cost-hint").hidden = items.length === 0;
  $("#selected-pagination").hidden = items.length <= SELECTED_PAGE_SIZE;
  $("#clear-selection").disabled = items.length === 0;
}

function renderComposition() {
  $("#selected-items-tab").textContent = `Выбранное (${number.format(state.candidates.size)})`;
  if (state.builderView === "catalog") renderCatalog();
  if (state.builderView === "selected") renderSelected();
}

function showBuilderView(name) {
  state.builderView = name;
  $$('[data-builder-panel]').forEach((panel) => { panel.hidden = panel.dataset.builderPanel !== name; });
  $$('.builder-tabs [data-builder-view]').forEach((button) => {
    const active = button.dataset.builderView === name;
    button.classList.toggle("secondary", !active);
    button.setAttribute("aria-pressed", String(active));
    if (active) button.focus({ preventScroll: true });
  });
  renderComposition();
  window.scrollTo({ top: 0 });
}

function renderOverview() {
  const selected = selectedItems();
  const totalRequirements = state.selectedRequirements.size;
  const evaluation = state.lastEvaluation;
  const coveredCount = evaluation?.covered?.length ?? 0;
  const coveragePercent = totalRequirements ? Math.round((coveredCount / totalRequirements) * 100) : 0;
  $("#stat-requirements").textContent = String(totalRequirements);
  $("#stat-mandatory").textContent = String(mandatoryIds().length);
  $("#stat-items").textContent = String(selected.length);
  $("#stat-cost").textContent = money(totalSelectedCost());
  $("#stat-period").textContent = `За ${periodNumber.format(state.periodMonths)} мес.`;
  $("#coverage-percent").textContent = evaluation ? `${coveragePercent}%` : "—";
  $("#coverage-ring").style.setProperty("--coverage", String(coveragePercent));
  $("#covered-count").textContent = evaluation ? String(evaluation.covered.length) : "—";
  $("#uncovered-count").textContent = evaluation ? String(evaluation.uncovered.length) : "—";
  $("#coverage-mandatory-count").textContent = String(mandatoryIds().length);
  const indicator = $("#mandatory-indicator");
  indicator.classList.toggle("is-good", Boolean(evaluation?.all_mandatory_covered));
  indicator.classList.toggle("is-bad", Boolean(evaluation && !evaluation.all_mandatory_covered));
  $("#mandatory-status-title").textContent = evaluation
    ? (evaluation.all_mandatory_covered ? "Все обязательные требования закрыты" : "Есть незакрытые обязательные требования")
    : "Оцените текущий набор";
  $("#mandatory-status-text").textContent = evaluation
    ? (evaluation.all_mandatory_covered ? "Текущий набор соответствует выбранному профилю по проверенным требованиям." : `Не закрыто обязательных требований: ${evaluation.uncovered_mandatory.length}.`)
    : "Результат проверки обязательных требований появится после расчёта.";
  $("#overview-selected-list").innerHTML = selected.length ? selected.slice(0, 5).map(({ item, total }) => (
    `<div class="mini-item"><span class="mini-item-copy"><strong>${escapeHtml(item.name)}</strong><small>${item.kind === "org" ? "Организационная мера" : "Средство защиты"}</small></span><strong class="mini-item-cost">${money(total)}</strong></div>`
  )).join("") : '<div class="empty-state"><strong>Набор пока пуст</strong><p>Перейдите к подбору и добавьте средства или организационные меры.</p></div>';
  $("#overview-total-cost").textContent = money(totalSelectedCost());
}

function renderEvaluation(result = state.lastEvaluation, source = state.resultSource) {
  const empty = $("#evaluation-empty");
  const list = $("#evaluation-requirements");
  if (!result) {
    empty.hidden = false;
    list.innerHTML = "";
    $("#evaluation-cost").textContent = "—";
    $("#evaluation-covered").textContent = "—";
    $("#evaluation-mandatory").textContent = "—";
    $("#evaluation-items").textContent = "—";
    $("#evaluation-banner").classList.remove("is-good", "is-bad");
    $("#evaluation-banner-title").textContent = "Набор готов к оценке";
    $("#evaluation-banner-text").textContent = "Запустите расчёт, чтобы проверить обязательные требования.";
    $("#evaluation-banner-status").textContent = "Нет расчёта";
    return;
  }
  empty.hidden = true;
  const selected = selectedItems();
  const requiredSet = new Set(state.selectedRequirements);
  const mandatory = new Set(mandatoryIds());
  const covered = new Set(result.covered ?? []);
  const coveredBy = result.covered_by ?? {};
  $("#evaluation-cost").textContent = money(result.total_cost);
  $("#evaluation-cost-period").textContent = `За ${periodNumber.format(state.periodMonths)} мес.`;
  $("#evaluation-covered").textContent = `${covered.size} из ${requiredSet.size}`;
  $("#evaluation-mandatory").textContent = `${mandatory.size - (result.uncovered_mandatory ?? []).length} из ${mandatory.size}`;
  $("#evaluation-mandatory-foot").textContent = result.all_mandatory_covered ? "Все обязательные закрыты" : `Не закрыто: ${(result.uncovered_mandatory ?? []).length}`;
  $("#evaluation-items").textContent = String(selected.length);
  const banner = $("#evaluation-banner");
  banner.classList.toggle("is-good", result.all_mandatory_covered);
  banner.classList.toggle("is-bad", !result.all_mandatory_covered);
  $("#evaluation-banner-title").textContent = result.all_mandatory_covered ? "Обязательные требования закрыты" : "Требуется доработать набор";
  $("#evaluation-banner-text").textContent = result.all_mandatory_covered
    ? `Покрыто ${covered.size} из ${requiredSet.size} требований. Общая стоимость рассчитана на выбранный период.`
    : `Не закрыто обязательных требований: ${(result.uncovered_mandatory ?? []).map((id) => id).join(", ") || "не определено"}.`;
  $("#evaluation-banner-status").textContent = source === "server" ? "Расчёт API" : "Примерный расчёт";
  const rows = state.requirements.filter((req) => requiredSet.has(req.id)).map((req) => {
    const isCovered = covered.has(req.id);
    const itemNames = (coveredBy[req.id] ?? []).map((itemId) => itemsById.get(itemId)?.name ?? itemId);
    return `<tr>
      <td><strong>${escapeHtml(req.id)}</strong> ${escapeHtml(req.title)}${mandatory.has(req.id) ? ' <span class="mandatory-pill">Обязательное</span>' : ""}<div class="result-req-meta">${escapeHtml(req.group || req.source || "")}</div></td>
      <td class="${isCovered ? "is-covered" : "is-uncovered"}">${isCovered ? escapeHtml(itemNames.join(", ") || "Закрыто") : "Не закрыто"}</td>
    </tr>`;
  }).join("");
  list.innerHTML = `<table><thead><tr><th scope="col">Требование</th><th scope="col">Чем закрыто</th></tr></thead><tbody>${rows}</tbody></table>`;
  if (source !== "server") {
    const explanation = state.usingExamples
      ? " Показатели рассчитаны локально на демонстрационных данных."
      : " Показатели рассчитаны локально по справочникам с сервера: серверный метод оценки пока недоступен.";
    $("#evaluation-banner-text").textContent += explanation;
  }
}

function updateBuilderSummary() {
  const total = totalSelectedCost();
  $("#builder-total-cost").textContent = money(total);
  $("#builder-period-label").textContent = `${periodNumber.format(state.periodMonths)} мес.`;
}

function renderOptimizerOptions() {
  const select = $("#algorithm-select");
  select.innerHTML = state.optimizers.map((optimizer) => (
    `<option value="${escapeHtml(optimizer.name)}">${escapeHtml(optimizer.title)} · ${optimizer.exact ? "точный" : "приближённый"}${state.usingExampleOptimizers ? " · пример" : ""}</option>`
  )).join("");
  if (state.optimizers.length) select.value = state.optimizers[0].name;
  updateAlgorithmDescription();
}

function updateAlgorithmDescription() {
  const optimizer = state.optimizers.find((entry) => entry.name === $("#algorithm-select").value);
  $("#algorithm-description").textContent = optimizer?.description || "Алгоритм будет использован при расчёте на сервере.";
}

function updateModeVisibility() {
  const mode = $("input[name='opt-mode']:checked")?.value ?? "min_cost";
  $$("[data-mode-card]").forEach((card) => card.classList.toggle("is-selected", card.dataset.modeCard === mode));
  $("#budget-field").hidden = mode !== "max_coverage";
}

function formatElapsed(elapsedMs) {
  const value = Number(elapsedMs);
  if (!Number.isFinite(value)) return "—";
  if (value < 1000) return `${Math.max(1, Math.round(value))} мс`;
  return `${(value / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} с`;
}

function renderSolution(solution, source = "example") {
  state.lastOptimization = solution;
  $("#solution-empty").hidden = true;
  $("#solution-result").hidden = false;
  $("#solution-cost").textContent = money(solution.cost);
  $("#solution-covered").textContent = `${solution.covered_count} из ${state.selectedRequirements.size}`;
  $("#solution-items-count").textContent = String(solution.selected.length);
  const elapsed = $("#solution-time");
  if (elapsed) elapsed.textContent = formatElapsed(solution.elapsed_ms);
  const selectedSet = new Set(solution.selected);
  const selectedItemsForResult = selectedItems().filter(({ item }) => selectedSet.has(item.id));
  $("#solution-items").innerHTML = selectedItemsForResult.length ? selectedItemsForResult.map(({ item, total }) => (
    `<div class="solution-item"><span>${escapeHtml(item.name)}</span><strong>${money(total)}</strong></div>`
  )).join("") : '<div class="empty-inline">Алгоритм не выбрал позиции из текущего набора.</div>';
  const chip = $("#solution-chip");
  chip.classList.toggle("is-success", Boolean(solution.feasible));
  chip.classList.toggle("is-warning", !solution.feasible);
  chip.textContent = solution.feasible ? "Допустимый вариант" : "Есть незакрытые требования";
  const foot = $("#solution-foot");
  foot.classList.toggle("is-good", Boolean(solution.feasible));
  foot.classList.toggle("is-bad", !solution.feasible);
  const sourceLabel = source === "server"
    ? "Результат получен от API."
    : state.usingExamples
      ? "Локальный пример на демонстрационных данных."
      : "Локальный расчёт по справочникам с сервера; серверный алгоритм пока недоступен.";
  foot.textContent = `${sourceLabel} ${solution.feasible ? "Обязательные требования закрыты." : `Не удалось закрыть все обязательные требования: ${(solution.uncovered_mandatory ?? []).join(", ") || "проверьте состав набора"}.`}`;
}

function renderPareto(solutions, selectedSolution = state.lastOptimization) {
  const container = $("#pareto-chart");
  if (!solutions?.length) {
    container.innerHTML = '<div class="chart-placeholder"><strong>Недостаточно данных для графика</strong><span>Добавьте позиции и запустите оптимизацию.</span></div>';
    return;
  }
  const width = 650;
  const height = 270;
  const left = 58;
  const top = 20;
  const plotWidth = 555;
  const plotHeight = 190;
  const maxCost = Math.max(1, ...solutions.map((entry) => Number(entry.cost) || 0));
  const maxCovered = Math.max(1, state.selectedRequirements.size, ...solutions.map((entry) => Number(entry.covered_count) || 0));
  const x = (cost) => left + (Math.max(0, Number(cost) || 0) / maxCost) * plotWidth;
  const y = (covered) => top + plotHeight - ((Number(covered) || 0) / maxCovered) * plotHeight;
  const grid = Array.from({ length: 5 }, (_, i) => {
    const yy = top + (plotHeight * i / 4);
    const tick = Math.round(maxCovered * (4 - i) / 4);
    return `<line x1="${left}" y1="${yy}" x2="${left + plotWidth}" y2="${yy}" stroke="#e9edf4" stroke-dasharray="3 4"/><text x="${left - 12}" y="${yy + 4}" text-anchor="end" fill="#8793a7" font-size="10">${tick}</text>`;
  }).join("");
  const ordered = [...solutions].sort((a, b) => (Number(a.cost) || 0) - (Number(b.cost) || 0));
  const frontierPath = ordered.map((entry, index) => `${index ? "L" : "M"} ${x(entry.cost)} ${y(entry.covered_count)}`).join(" ");
  const frontier = ordered.length > 1
    ? `<path d="${frontierPath}" fill="none" stroke="#5d82d6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="4 4"/>`
    : "";
  const points = ordered.map((entry) => {
    const active = selectedSolution && Array.isArray(selectedSolution.selected) &&
      entry.selected?.length === selectedSolution.selected.length &&
      entry.selected.every((id) => selectedSolution.selected.includes(id)) &&
      Math.round(entry.cost) === Math.round(selectedSolution.cost);
    const px = x(entry.cost);
    const py = y(entry.covered_count);
    const color = active ? "#18825b" : entry.feasible ? "#3169e8" : "#d79a2b";
    return `<g><title>Стоимость: ${escapeHtml(money(entry.cost))}; закрыто требований: ${entry.covered_count}; ${entry.feasible ? "допустимый вариант" : "не все обязательные требования закрыты"}</title><circle cx="${px}" cy="${py}" r="${active ? 6 : 4.5}" fill="${color}" fill-opacity="${active ? 1 : .82}" stroke="#fff" stroke-width="2"/></g>`;
  }).join("");
  const labels = `<text x="${left + plotWidth / 2}" y="258" text-anchor="middle" fill="#77849a" font-size="10">Стоимость за период, ₽</text><text transform="translate(15 ${top + plotHeight / 2}) rotate(-90)" text-anchor="middle" fill="#77849a" font-size="10">Закрыто требований</text><text x="${left}" y="229" text-anchor="start" fill="#8793a7" font-size="10">0</text><text x="${left + plotWidth}" y="229" text-anchor="end" fill="#8793a7" font-size="10">${escapeHtml(number.format(maxCost))}</text>`;
  container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="График стоимости и числа закрытых требований">${grid}<line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" stroke="#ccd4e1"/><line x1="${left}" y1="${top + plotHeight}" x2="${left + plotWidth}" y2="${top + plotHeight}" stroke="#ccd4e1"/>${frontier}${points}${labels}</svg>`;
}

function renderAll() {
  renderApiState();
  renderProfileOptions();
  renderRequirements();
  renderComposition();
  renderOverview();
  updateBuilderSummary();
  renderEvaluation();
}

function invalidateResults() {
  queueDraftSave();
  state.lastEvaluation = null;
  state.resultSource = "none";
  state.lastOptimization = null;
  if (state.lastPareto.length) renderPareto([]);
  state.lastPareto = [];
  $("#solution-empty").hidden = false;
  $("#solution-result").hidden = true;
  $("#solution-chip").classList.remove("is-success", "is-warning");
  $("#solution-chip").textContent = "Ожидает расчёта";
  renderEvaluation(null, "none");
}

function navigateTo(name) {
  const section = $(`[data-page-section="${name}"]`);
  if (!section) return;
  $$('[data-page-section]').forEach((entry) => {
    entry.hidden = entry.dataset.pageSection !== name;
  });
  $$(".workspace-nav [data-page]").forEach((button) => {
    const active = button.dataset.page === name;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  document.title = `${$("h1", section).textContent} — СППР`;
  window.scrollTo({ top: 0 });
  if (name === "evaluation" && !state.lastEvaluation) runEvaluation();
}

async function runEvaluation() {
  if (state.isCalculating) return;
  if (!state.selectedRequirements.size) {
    showToast("Выберите хотя бы одно требование для оценки.", "error");
    navigateTo("builder");
    showBuilderView("scenario");
    return;
  }
  if (!requireCandidatePrices()) return;
  state.isCalculating = true;
  const button = $("#run-evaluation");
  setLoading(button, true, "Считаем…");
  const scenario = scenarioFor();
  try {
    const result = await workspaceService.evaluate(scenario);
    state.lastEvaluation = result;
    state.resultSource = "server";
    if (state.usingExamples) throw new Error("Каталоги используют примерные данные; оценка также будет примерной.");
    renderEvaluation(result, "server");
    showToast("Оценка получена от сервера.", "success");
  } catch (error) {
    const result = localEvaluate(scenario);
    state.lastEvaluation = result;
    state.resultSource = "example";
    if (!state.problems.includes("Оценка: серверный метод недоступен, выполнен локальный расчёт")) state.problems.push("Оценка: серверный метод недоступен, выполнен локальный расчёт");
    renderApiState();
    renderEvaluation(result, "example");
    showToast(state.usingExamples
      ? "Показан локальный расчёт на демонстрационных данных."
      : "API оценки пока недоступен: результат рассчитан локально по данным сервера.", "info");
  } finally {
    state.isCalculating = false;
    setLoading(button, false);
    renderOverview();
  }
}

async function runOptimization() {
  if (state.isCalculating) return;
  if (!state.selectedRequirements.size) {
    showToast("Сначала выберите требования.", "error");
    navigateTo("builder");
    showBuilderView("scenario");
    return;
  }
  if (!state.candidates.size) {
    showToast("Добавьте в набор хотя бы одно средство или организационную меру.", "error");
    navigateTo("builder");
    showBuilderView("catalog");
    return;
  }
  if (!requireCandidatePrices()) return;
  const mode = $("input[name='opt-mode']:checked")?.value ?? "min_cost";
  const budget = mode === "max_coverage" ? Number($("#budget-input").value) : null;
  if (mode === "max_coverage" && (!Number.isFinite(budget) || budget < 0)) {
    showToast("Укажите бюджет не меньше нуля.", "error");
    return;
  }
  const payload = {
    scenario: scenarioFor(),
    algorithm: $("#algorithm-select").value,
    mode,
    ...(mode === "max_coverage" ? { budget } : {}),
  };
  state.isCalculating = true;
  const button = $("#run-optimization");
  const stopButton = $("#stop-optimization");
  const controller = new AbortController();
  state.optimizationAbort = controller;
  if (stopButton) stopButton.hidden = false;
  setLoading(button, true, "Подбираем…");
  let solution;
  let solutionSource = "server";
  let paretoSource = "server";
  let stopped = false;
  try {
    if (state.usingExamples) throw new Error("Примерные справочники");
    solution = await workspaceService.optimize(payload, controller.signal);
  } catch (error) {
    if (error?.name === "AbortError") {
      stopped = true;
    } else {
      solution = localOptimize(payload);
      solutionSource = "example";
      paretoSource = "example";
      if (!state.problems.includes("Оптимизация: серверный метод недоступен, выполнен локальный расчёт")) state.problems.push("Оптимизация: серверный метод недоступен, выполнен локальный расчёт");
      renderApiState();
    }
  }
  try {
    if (stopped) return;
    let pareto;
    if (paretoSource === "server") {
      try {
        pareto = await workspaceService.pareto(payload, controller.signal);
      } catch (error) {
        if (error?.name === "AbortError") {
          stopped = true;
          return;
        }
        pareto = localPareto(payload.scenario);
        paretoSource = "example";
        if (!state.problems.includes("Фронт Парето: серверный метод недоступен, построен локальный график")) state.problems.push("Фронт Парето: серверный метод недоступен, построен локальный график");
        renderApiState();
      }
    } else {
      pareto = localPareto(payload.scenario);
    }
    state.lastPareto = Array.isArray(pareto) ? pareto : [];
  } finally {
    if (stopButton) stopButton.hidden = true;
    state.optimizationAbort = null;
    state.isCalculating = false;
    setLoading(button, false);
    if (stopped) {
      showToast("Расчёт остановлен.", "info");
      return;
    }
    state.lastOptimization = solution;
    renderSolution(solution, solutionSource);
    renderPareto(state.lastPareto, solution);
    showToast(solutionSource === "server"
      ? "Подбор завершён на сервере."
      : state.usingExamples
        ? "Показан локальный подбор на демонстрационных данных."
        : "API оптимизации пока недоступен: вариант подобран локально по данным сервера.", solutionSource === "server" ? "success" : "info");
  }
}

async function stopOptimization() {
  const controller = state.optimizationAbort;
  try {
    await workspaceService.cancelOptimization();
  } catch {
    /* сервер уже завершил расчёт */
  }
  controller?.abort();
}

let draftPath;
let draftSave = Promise.resolve();
let draftDirty = false;
let draftSaveFailed = false;

function queueDraftSave() {
  if (!draftPath || !state.initializedOnce || state.usingExamples) return;
  draftDirty = true;
  draftSave = draftSave.then(async () => {
    if (!draftDirty) return;
    draftDirty = false;
    await apiRequest(draftPath, {
      method: "PUT",
      body: {
        profile_id: state.profileId,
        period_months: state.periodMonths,
        requirements: [...state.selectedRequirements],
        candidates: [...state.candidates.keys()],
        prices: Object.fromEntries(state.prices),
        algorithm: $("#algorithm-select").value,
        mode: $("input[name='opt-mode']:checked").value,
        budget: $("#budget-input").value,
      },
    });
    draftSaveFailed = false;
  }).catch(() => {
    draftSaveFailed = true;
    showToast("Не удалось сохранить черновик. Повторите изменение или попробуйте выйти ещё раз.", "error");
  });
}

function restoreDraft(draft) {
  state.profileId = draft.profile_id;
  state.periodMonths = draft.period_months;
  $("#period-input").value = draft.period_months;
  state.selectedRequirements = new Set(draft.requirements);
  state.prices = new Map(Object.entries(draft.prices));
  state.candidates = new Map(draft.candidates.map((id) => [
    id, { ...(state.prices.get(id) ?? { capex: "", opex_month: "" }) },
  ]));
  $("input[name='opt-mode'][value='" + draft.mode + "']").checked = true;
  $("#budget-input").value = draft.budget;
  updateModeVisibility();
}

function selectItem(itemId) {
  if (state.candidates.has(itemId)) {
    state.candidates.delete(itemId);
  } else {
    const item = itemsById.get(itemId);
    if (!item) return;
    state.candidates.set(itemId, { ...priceFor(item) });
  }
  updateComposition();
}

function updateComposition() {
  invalidateResults();
  renderComposition();
  renderOverview();
  updateBuilderSummary();
}

function onRequirementChange(event) {
  const input = event.target.closest("input[data-requirement-id]");
  if (!input) return;
  const requirementId = input.dataset.requirementId;
  if (mandatoryIds().includes(requirementId)) {
    state.selectedRequirements.add(requirementId);
    input.checked = true;
    return;
  }
  if (input.checked) state.selectedRequirements.add(requirementId);
  else state.selectedRequirements.delete(requirementId);
  invalidateResults();
  renderAll();
}

function onCostChange(event) {
  const input = event.target.closest("input[data-cost-item][data-cost-field]");
  if (!input) return;
  const itemId = input.dataset.costItem;
  const field = input.dataset.costField;
  if (input.validity.badInput) return;
  const parsed = input.value.trim() === "" ? "" : Math.max(0, Number(input.value) || 0);
  if (event.type === "change") input.value = String(parsed);
  const current = { ...(state.candidates.get(itemId) ?? priceFor(itemsById.get(itemId) ?? {})) };
  current[field] = parsed;
  state.candidates.set(itemId, current);
  state.prices.set(itemId, current);
  invalidateResults();
  renderOverview();
  updateBuilderSummary();
}

function bindEvents() {
  $$('[data-page]').forEach((control) => control.addEventListener("click", () => navigateTo(control.dataset.page)));
  $("#profile-select").addEventListener("change", (event) => {
    const oldMandatory = mandatoryIds();
    state.profileId = event.target.value;
    const newMandatory = new Set(mandatoryIds());
    oldMandatory.forEach((id) => {
      if (!newMandatory.has(id)) state.selectedRequirements.delete(id);
    });
    mandatoryRequirementsAreIncluded();
    invalidateResults();
    renderAll();
  });
  $("#period-input").addEventListener("input", (event) => {
    const input = event.target;
    if (!input.validity.valid || input.value === "") return;
    state.periodMonths = Number(input.value);
    invalidateResults();
    updateBuilderSummary();
  });
  $("#period-input").addEventListener("change", (event) => {
    const raw = Number(event.target.value);
    const value = Math.min(120, Math.max(0.1, Math.round((Number.isFinite(raw) && event.target.value !== "" ? raw : 12) * 10) / 10));
    state.periodMonths = value;
    event.target.value = String(value);
    invalidateResults();
    renderOverview();
    updateBuilderSummary();
  });
  $("#requirements-list").addEventListener("change", onRequirementChange);
  let requirementSearchTimer;
  $("#requirement-search").addEventListener("input", (event) => {
    state.requirementSearch = event.target.value;
    clearTimeout(requirementSearchTimer);
    requirementSearchTimer = setTimeout(renderRequirements, 180);
  });
  $("#requirement-group-filter").addEventListener("change", (event) => {
    state.requirementGroup = event.target.value;
    renderRequirements();
  });
  $$('[data-requirement-filter]').forEach((button) => button.addEventListener("click", () => {
    state.requirementFilter = button.dataset.requirementFilter;
    renderRequirements();
  }));
  $("#toggle-requirements").addEventListener("click", () => {
    const allSelected = state.requirements.every((req) => state.selectedRequirements.has(req.id));
    if (allSelected) state.selectedRequirements = new Set(mandatoryIds());
    else state.selectedRequirements = new Set(state.requirements.map((entry) => entry.id));
    mandatoryRequirementsAreIncluded();
    invalidateResults();
    renderAll();
  });
  $$('[data-builder-view]').forEach((button) => {
    button.addEventListener("click", () => showBuilderView(button.dataset.builderView));
  });
  const toggleItem = (event) => {
    const button = event.target.closest("[data-toggle-item]");
    if (!button) return;
    const selector = "[data-toggle-item]";
    const index = $$(selector, event.currentTarget).indexOf(button);
    selectItem(button.dataset.toggleItem);
    const remaining = $$(selector, event.currentTarget);
    (remaining[Math.min(index, remaining.length - 1)] ?? $("#selected-items-tab")).focus({ preventScroll: true });
  };
  $("#catalog-list").addEventListener("click", toggleItem);
  $("#selected-list").addEventListener("click", toggleItem);
  $("#selected-list").addEventListener("input", onCostChange);
  $("#selected-list").addEventListener("change", onCostChange);
  $$('[data-catalog-step]').forEach((button) => button.addEventListener("click", () => {
    state.catalogPage += Number(button.dataset.catalogStep);
    renderCatalog();
    $("#catalog-list").scrollTop = 0;
  }));
  $$('[data-selected-step]').forEach((button) => button.addEventListener("click", () => {
    state.selectedPage += Number(button.dataset.selectedStep);
    renderSelected();
  }));
  $("#catalog-page-size").addEventListener("change", () => {
    state.catalogPage = 0;
    renderCatalog();
  });
  let searchTimer;
  $("#catalog-search").addEventListener("input", (event) => {
    state.search = event.target.value;
    state.catalogPage = 0;
    $("#catalog-select-page").disabled = true;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderCatalog, 150);
  });
  $$(".catalog-tab").forEach((tab) => tab.addEventListener("click", () => {
    state.activeKind = tab.dataset.kind;
    state.catalogPage = 0;
    $$(".catalog-tab").forEach((other) => other.classList.toggle("is-active", other === tab));
    renderCatalog();
  }));
  $("#catalog-select-page").addEventListener("click", () => {
    for (const item of state.catalogPageItems) {
      if (!state.candidates.has(item.id)) state.candidates.set(item.id, { ...priceFor(item) });
    }
    updateComposition();
  });
  $("#clear-selection").addEventListener("click", () => {
    state.candidates.clear();
    updateComposition();
  });
  $("#run-evaluation").addEventListener("click", runEvaluation);
  $("#run-optimization").addEventListener("click", runOptimization);
  $("#algorithm-select").addEventListener("change", () => {
    updateAlgorithmDescription();
    queueDraftSave();
  });
  $("#budget-input").addEventListener("input", queueDraftSave);
  $$('input[name="opt-mode"]').forEach((input) => input.addEventListener("change", () => {
    updateModeVisibility();
    queueDraftSave();
  }));
  $("#stop-optimization")?.addEventListener("click", stopOptimization);
  $("#refresh-data").addEventListener("click", async () => {
    showToast("Обновляем справочники…");
    await loadPageData();
    showToast("Справочники обновлены.", "success");
  });
  $("#notice-close").addEventListener("click", () => { $("#data-notice").hidden = true; });
  $("#logout-button").addEventListener("click", async () => {
    try {
      if (draftSaveFailed) queueDraftSave();
      await draftSave;
      if (draftSaveFailed) return;
      await apiRequest("/auth/logout", { method: "POST" });
      window.location.assign("/");
    } catch (error) {
      showToast(error.message, "error");
    }
  });
}

async function loadPageData(draft = null) {
  const previousAlgorithm = draft?.algorithm ?? $("#algorithm-select").value;
  const result = await workspaceService.loadCatalogs();
  state.requirements = result.requirements;
  state.items = result.items;
  itemsById = new Map(state.items.map((item) => [item.id, item]));
  requirementsById = new Map(state.requirements.map((requirement) => [requirement.id, requirement]));
  catalogFilter = null;
  const tools = state.items.filter((item) => item.kind === "tool").length;
  $('[data-kind="all"]').textContent = `Все (${number.format(state.items.length)})`;
  $('[data-kind="tool"]').textContent = `Средства (${number.format(tools)})`;
  $('[data-kind="org"]').textContent = `Оргмеры (${number.format(state.items.length - tools)})`;
  state.profiles = [...result.profiles].sort((a, b) => String(a.id).localeCompare(String(b.id), "ru", { numeric: true }));
  state.optimizers = result.optimizers;
  state.usingExamples = result.usingExamples;
  state.usingExampleOptimizers = result.usingExampleOptimizers;
  state.catalogsEmpty = result.catalogsEmpty;
  state.serverOnline = result.serverOnline;
  state.problems = result.problems;

  if (draft) restoreDraft(draft);
  state.profileId = state.profiles.some((entry) => entry.id === state.profileId)
    ? state.profileId
    : (state.profiles[0]?.id ?? "");
  const validRequirementIds = new Set(state.requirements.map((entry) => entry.id));
  state.selectedRequirements = new Set([...state.selectedRequirements].filter((id) => validRequirementIds.has(id)));
  if (!state.initializedOnce && !draft) {
    state.selectedRequirements = new Set(mandatoryIds());
  }
  mandatoryRequirementsAreIncluded();
  for (const itemId of state.candidates.keys()) {
    if (!itemsById.has(itemId)) state.candidates.delete(itemId);
  }
  state.initializedOnce = true;
  renderOptimizerOptions();
  if (state.optimizers.some((optimizer) => optimizer.name === previousAlgorithm)) {
    $("#algorithm-select").value = previousAlgorithm;
    updateAlgorithmDescription();
  }
  renderAll();
}

async function initialize() {
  const account = await apiRequest("/auth/me");
  const path = "/users/" + account.id + "/draft";
  let draft = null;
  try {
    draft = await apiRequest(path);
    draftPath = path;
  } catch (error) {
    if (error.status === 401) throw error;
    showToast("Не удалось загрузить черновик. Сохранение временно недоступно.", "error");
  }
  await loadPageData(draft);
  $("#workspace-account").textContent = account.login;
  bindEvents();
  updateModeVisibility();
  $("#page-builder").inert = false;
  $("#workspace-loading").hidden = true;
}

initialize().catch((error) => {
  if (error?.status === 401) {
    window.location.replace("/");
    return;
  }
  $("#workspace-loading").hidden = true;
  $("#data-notice-text").textContent = error?.message || "Не удалось загрузить справочники.";
  $("#data-notice").hidden = false;
});
