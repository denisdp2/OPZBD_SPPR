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
  usingExamples: true,
  serverOnline: false,
  problems: [],
  lastEvaluation: null,
  lastOptimization: null,
  lastPareto: [],
  resultSource: "none",
  isCalculating: false,
  initializedOnce: false,
};

const currency = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 });
const number = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

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

function hasMissingCosts() {
  return selectedItems().some(({ costs }) => (
    costs.capex === "" || costs.capex === null || costs.capex === undefined ||
    costs.opex_month === "" || costs.opex_month === null || costs.opex_month === undefined
  ));
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
      const item = state.items.find((entry) => entry.id === itemId);
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
      const costs = state.candidates.get(itemId) ?? priceFor(state.items.find((item) => item.id === itemId) ?? {});
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
  const apiStatus = $("#api-status");
  const notice = $("#data-notice");
  const footerState = $("#footer-data-state");
  if (apiStatus) {
    apiStatus.classList.toggle("is-online", state.serverOnline && !state.usingExamples);
    apiStatus.classList.toggle("is-demo", state.usingExamples);
    const label = apiStatus.querySelector("span:last-child");
    if (label) label.textContent = state.usingExamples
      ? (state.serverOnline ? "Примерные данные" : "Локальный режим просмотра")
      : "Данные с сервера";
    apiStatus.title = state.problems.join("; ") || (state.serverOnline ? "API доступно" : "Нет соединения с API");
  }
  if (notice) notice.hidden = !state.usingExamples;
  if (footerState) footerState.textContent = state.usingExamples ? "Отображаются примерные данные" : "Справочники загружены с сервера";
}

function renderProfileOptions() {
  const select = $("#profile-select");
  if (!select) return;
  select.innerHTML = state.profiles.map((entry) => (
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
  list.innerHTML = state.requirements.map((req) => {
    const isMandatory = mandatory.has(req.id);
    const checked = isMandatory || state.selectedRequirements.has(req.id);
    return `<label class="requirement-choice${isMandatory ? " is-mandatory" : ""}">
      <input type="checkbox" data-requirement-id="${escapeHtml(req.id)}" ${checked ? "checked" : ""} ${isMandatory ? "disabled" : ""}>
      <span class="requirement-choice-copy">
        <strong>${escapeHtml(req.title)}${isMandatory ? ' <span class="mandatory-pill">Обязательное</span>' : ""}</strong>
        <small>${escapeHtml(req.id)}${req.group ? ` · ${escapeHtml(req.group)}` : ""}${req.source ? ` · ${escapeHtml(req.source)}` : ""}</small>
      </span>
    </label>`;
  }).join("") || `<div class="empty-inline">Нет требований для отображения.</div>`;
  $("#requirements-selected-count").textContent = String(state.selectedRequirements.size);
  $("#requirements-total-count").textContent = String(state.requirements.length);
  $("#mandatory-in-scenario").textContent = String(mandatoryIds().length);
  $("#excluded-in-scenario").textContent = String(Math.max(0, state.requirements.length - state.selectedRequirements.size));
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

function miniIcon(kind) {
  if (kind === "org") {
    return '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 3.5h8l4 4v13H7z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M15 3.8v4h4M10 12h6M10 15.5h6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';
  }
  return '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="4" y="5" width="16" height="14" rx="2" stroke="currentColor" stroke-width="1.7"/><path d="M8 9h8M8 12h5M8 15h8" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';
}

function renderCatalog() {
  const list = $("#catalog-list");
  if (!list) return;
  const search = state.search.trim().toLocaleLowerCase("ru");
  const filtered = state.items.filter((item) => {
    const kindMatches = state.activeKind === "all" || item.kind === state.activeKind;
    const searchable = `${item.name} ${item.description ?? ""} ${item.id} ${item.vendor ?? ""} ${item.fstec_cert_no ?? ""} ${item.in_ru_software_registry ? "российское по реестр" : ""}`.toLocaleLowerCase("ru");
    return kindMatches && (!search || searchable.includes(search));
  });
  list.innerHTML = filtered.map((item) => {
    const selected = state.candidates.has(item.id);
    const costs = selected ? state.candidates.get(item.id) : priceFor(item);
    const covers = (item.covers ?? []).map((id) => {
      const req = state.requirements.find((entry) => entry.id === id);
      return `<span class="cover-chip">${escapeHtml(req?.id ?? id)}</span>`;
    }).join("");
    const facts = item.kind === "tool" ? `
      <div class="item-facts" aria-label="Сведения о средстве защиты">
        <span class="item-fact ${item.fstec_certified ? "is-positive" : "is-muted"}">${item.fstec_certified ? `Сертификат ФСТЭК${item.fstec_cert_no ? ` · № ${escapeHtml(item.fstec_cert_no)}` : ""}${item.fstec_cert_valid_until ? ` · до ${escapeHtml(item.fstec_cert_valid_until)}` : ""}` : "Без сертификата ФСТЭК"}</span>
        <span class="item-fact ${item.in_ru_software_registry ? "is-positive" : "is-muted"}">${item.in_ru_software_registry ? "В реестре российского ПО" : "Не в реестре российского ПО"}</span>
        ${item.vendor ? `<span class="item-fact">Производитель: ${escapeHtml(item.vendor)}</span>` : ""}
      </div>` : (item.implement_days !== null && item.implement_days !== undefined
        ? `<div class="item-facts"><span class="item-fact">Срок внедрения: ${escapeHtml(item.implement_days)} дн.</span></div>` : "");
    return `<article class="catalog-item${selected ? " is-selected" : ""}">
      <div class="catalog-item-icon">${miniIcon(item.kind)}</div>
      <div class="catalog-item-main">
        <div class="catalog-item-title-row"><strong class="catalog-item-title">${escapeHtml(item.name)}</strong><span class="kind-tag${item.kind === "org" ? " kind-org" : ""}">${item.kind === "org" ? "Организационная мера" : "Средство защиты"}</span></div>
        <p class="catalog-description">${escapeHtml(item.description || "Описание не указано.")}</p>
        ${facts}
        <div class="covers-label">Связанные требования</div>
        <div class="covers-row">${covers || '<span class="cover-chip">Связи не заданы</span>'}</div>
        ${selected ? `<div class="cost-editor">
          <label>Внедрение, ₽<span class="cost-input-wrap"><input type="number" min="0" step="1" placeholder="0" value="${costs.capex === null || costs.capex === undefined ? "" : escapeHtml(costs.capex)}" data-cost-item="${escapeHtml(item.id)}" data-cost-field="capex" aria-label="Стоимость внедрения: ${escapeHtml(item.name)}"><span>₽</span></span></label>
          <label>Эксплуатация в месяц, ₽<span class="cost-input-wrap"><input type="number" min="0" step="1" placeholder="0" value="${costs.opex_month === null || costs.opex_month === undefined ? "" : escapeHtml(costs.opex_month)}" data-cost-item="${escapeHtml(item.id)}" data-cost-field="opex_month" aria-label="Стоимость эксплуатации в месяц: ${escapeHtml(item.name)}"><span>₽</span></span></label>
        </div>` : ""}
      </div>
      <button type="button" class="catalog-item-select" data-toggle-item="${escapeHtml(item.id)}" aria-label="${selected ? "Убрать из набора" : "Добавить в набор"}: ${escapeHtml(item.name)}" aria-pressed="${selected}">${selected ? '<svg viewBox="0 0 24 24" fill="none"><path d="m5 12 4 4L19 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' : '<svg viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'}</button>
    </article>`;
  }).join("") || `<div class="empty-state"><div class="empty-illustration">⌕</div><strong>Ничего не найдено</strong><p>Измените запрос или выберите другую категорию.</p></div>`;
  $("#catalog-total").textContent = `${state.items.length} позиций`;
  $("#catalog-visible-count").textContent = `Показано ${filtered.length} из ${state.items.length}`;
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
  $("#stat-period").textContent = `За ${number.format(state.periodMonths)} ${state.periodMonths === 1 ? "месяц" : state.periodMonths < 5 ? "месяца" : "месяцев"}`;
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
    `<div class="mini-item"><span class="mini-item-icon">${miniIcon(item.kind)}</span><span class="mini-item-copy"><strong>${escapeHtml(item.name)}</strong><small>${item.kind === "org" ? "Организационная мера" : "Средство защиты"}</small></span><strong class="mini-item-cost">${money(total)}</strong></div>`
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
  $("#evaluation-cost-period").textContent = `За ${number.format(state.periodMonths)} месяцев`;
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
  list.innerHTML = state.requirements.filter((req) => requiredSet.has(req.id)).map((req) => {
    const isCovered = covered.has(req.id);
    const itemNames = (coveredBy[req.id] ?? []).map((itemId) => state.items.find((item) => item.id === itemId)?.name ?? itemId);
    return `<div class="result-requirement">
      <div class="result-req-main"><div class="result-req-title"><span class="result-req-code">${escapeHtml(req.id)}</span>${escapeHtml(req.title)}${mandatory.has(req.id) ? ' <span class="mandatory-pill">Обязательное</span>' : ""}</div><div class="result-req-meta">${escapeHtml(req.group || req.source || "Требование")}</div></div>
      <div class="coverage-bar-wrap"><div class="coverage-bar"><span class="${isCovered ? "" : "is-uncovered"}" style="width:${isCovered ? 100 : 0}%"></span></div><span class="coverage-bar-label">${isCovered ? "100%" : "0%"}</span></div>
      <span class="coverage-state ${isCovered ? "is-covered" : "is-uncovered"}"><i class="legend-dot ${isCovered ? "dot-green" : "dot-amber"}"></i>${isCovered ? escapeHtml(itemNames.join(", ") || "Закрыто") : "Не закрыто"}</span>
    </div>`;
  }).join("");
  if (source !== "server") {
    // Local calculation is deliberately labelled, because API handlers currently may be unavailable.
    $("#evaluation-banner-text").textContent += " Показатели рассчитаны в интерфейсе на примере данных.";
  }
}

function updateBuilderSummary() {
  const chosen = selectedItems();
  const total = totalSelectedCost();
  $("#builder-item-count").textContent = `${chosen.length} позиций выбрано`;
  $("#builder-total-cost").textContent = money(total);
  $("#builder-period-label").textContent = `${number.format(state.periodMonths)} ${state.periodMonths === 1 ? "месяц" : state.periodMonths < 5 ? "месяца" : "месяцев"}`;
  $("#nav-selected-count").textContent = String(chosen.length);
}

function renderOptimizerOptions() {
  const select = $("#algorithm-select");
  select.innerHTML = state.optimizers.map((optimizer) => (
    `<option value="${escapeHtml(optimizer.name)}">${escapeHtml(optimizer.title)} · ${optimizer.exact ? "точный" : "приближённый"}</option>`
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

function renderSolution(solution, source = "example") {
  state.lastOptimization = solution;
  $("#solution-empty").hidden = true;
  $("#solution-result").hidden = false;
  $("#solution-cost").textContent = money(solution.cost);
  $("#solution-covered").textContent = `${solution.covered_count} из ${state.selectedRequirements.size}`;
  $("#solution-items-count").textContent = String(solution.selected.length);
  const selectedSet = new Set(solution.selected);
  const selectedItemsForResult = selectedItems().filter(({ item }) => selectedSet.has(item.id));
  $("#solution-items").innerHTML = selectedItemsForResult.length ? selectedItemsForResult.map(({ item, total }) => (
    `<div class="solution-item"><span class="mini-item-icon">${miniIcon(item.kind)}</span><span>${escapeHtml(item.name)}</span><strong>${money(total)}</strong></div>`
  )).join("") : '<div class="empty-inline">Алгоритм не выбрал позиции из текущего набора.</div>';
  const chip = $("#solution-chip");
  chip.classList.toggle("is-success", Boolean(solution.feasible));
  chip.classList.toggle("is-warning", !solution.feasible);
  chip.textContent = solution.feasible ? "Допустимый вариант" : "Есть незакрытые требования";
  const foot = $("#solution-foot");
  foot.classList.toggle("is-good", Boolean(solution.feasible));
  foot.classList.toggle("is-bad", !solution.feasible);
  foot.textContent = `${source === "server" ? "Результат получен от API." : "Примерный результат рассчитан в интерфейсе."} ${solution.feasible ? "Обязательные требования закрыты." : `Не удалось закрыть все обязательные требования: ${(solution.uncovered_mandatory ?? []).join(", ") || "проверьте состав набора"}.`}`;
}

function renderPareto(solutions, selectedSolution = state.lastOptimization) {
  const container = $("#pareto-chart");
  if (!solutions?.length) {
    container.innerHTML = '<div class="chart-placeholder"><span class="chart-placeholder-icon">↗</span><strong>Недостаточно данных для графика</strong><span>Добавьте позиции и запустите оптимизацию.</span></div>';
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
  const maxCoverage = Math.max(...solutions.map((entry) => Number(entry.covered_count) || 0));
  const labels = `<text x="${left + plotWidth / 2}" y="258" text-anchor="middle" fill="#77849a" font-size="10">Стоимость за период, ₽</text><text transform="translate(15 ${top + plotHeight / 2}) rotate(-90)" text-anchor="middle" fill="#77849a" font-size="10">Закрыто требований</text><text x="${left}" y="229" text-anchor="start" fill="#8793a7" font-size="10">0</text><text x="${left + plotWidth}" y="229" text-anchor="end" fill="#8793a7" font-size="10">${escapeHtml(number.format(maxCost))}</text>`;
  container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="График стоимости и числа закрытых требований">${grid}<line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" stroke="#ccd4e1"/><line x1="${left}" y1="${top + plotHeight}" x2="${left + plotWidth}" y2="${top + plotHeight}" stroke="#ccd4e1"/>${frontier}${points}${labels}</svg>`;
}

function renderAll() {
  renderApiState();
  renderProfileOptions();
  renderRequirements();
  renderCatalog();
  renderOverview();
  updateBuilderSummary();
  renderEvaluation();
}

function invalidateResults() {
  state.lastEvaluation = null;
  state.resultSource = "none";
  state.lastOptimization = null;
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
    const active = entry.dataset.pageSection === name;
    entry.hidden = !active;
    entry.classList.toggle("is-visible", active);
  });
  $$(".nav-link[data-page]").forEach((link) => link.classList.toggle("is-active", link.dataset.page === name));
  const captions = { overview: "Рабочий стол", builder: "Состав набора", evaluation: "Оценка набора", optimization: "Оптимизация" };
  $("#breadcrumb-current").textContent = captions[name] ?? "Рабочая область";
  $(".sidebar").classList.remove("is-open");
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (name === "evaluation" && !state.lastEvaluation) runEvaluation();
}

async function runEvaluation() {
  if (state.isCalculating) return;
  if (!state.selectedRequirements.size) {
    showToast("Выберите хотя бы одно требование для оценки.", "error");
    navigateTo("builder");
    return;
  }
  if (state.candidates.size && hasMissingCosts()) {
    showToast("Заполните стоимость внедрения и эксплуатации для каждой выбранной позиции. Если затраты отсутствуют, укажите 0.", "error");
    navigateTo("builder");
    return;
  }
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
    state.usingExamples = true;
    if (!state.problems.includes("Оценка: используется локальный расчёт")) state.problems.push("Оценка: используется локальный расчёт");
    renderApiState();
    renderEvaluation(result, "example");
    showToast("Показан примерный расчёт. Серверный метод оценки пока недоступен.", "info");
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
    return;
  }
  if (!state.candidates.size) {
    showToast("Добавьте в набор хотя бы одно средство или организационную меру.", "error");
    navigateTo("builder");
    return;
  }
  if (hasMissingCosts()) {
    showToast("Заполните стоимость внедрения и эксплуатации для каждой выбранной позиции. Если затраты отсутствуют, укажите 0.", "error");
    navigateTo("builder");
    return;
  }
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
  setLoading(button, true, "Подбираем…");
  let solution;
  let solutionSource = "server";
  let paretoSource = "server";
  try {
    if (state.usingExamples) throw new Error("Примерные справочники");
    solution = await workspaceService.optimize(payload);
  } catch {
    solution = localOptimize(payload);
    solutionSource = "example";
    paretoSource = "example";
    state.usingExamples = true;
    if (!state.problems.includes("Оптимизация: используется локальный расчёт")) state.problems.push("Оптимизация: используется локальный расчёт");
    renderApiState();
  }
  try {
    let pareto;
    if (paretoSource === "server") {
      try {
        pareto = await workspaceService.pareto(payload);
      } catch {
        pareto = localPareto(payload.scenario);
        paretoSource = "example";
        state.usingExamples = true;
        renderApiState();
      }
    } else {
      pareto = localPareto(payload.scenario);
    }
    state.lastPareto = Array.isArray(pareto) ? pareto : [];
  } finally {
    state.lastOptimization = solution;
    renderSolution(solution, solutionSource);
    renderPareto(state.lastPareto, solution);
    state.isCalculating = false;
    setLoading(button, false);
    showToast(solutionSource === "server" ? "Подбор завершён." : "Показан примерный вариант подбора.", solutionSource === "server" ? "success" : "info");
  }
}

function selectItem(itemId) {
  if (state.candidates.has(itemId)) {
    state.candidates.delete(itemId);
  } else {
    const item = state.items.find((entry) => entry.id === itemId);
    if (!item) return;
    state.candidates.set(itemId, { ...priceFor(item) });
  }
  invalidateResults();
  renderAll();
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
  const parsed = input.value.trim() === "" ? "" : Math.max(0, Number(input.value) || 0);
  input.value = String(parsed);
  const current = { ...(state.candidates.get(itemId) ?? priceFor(state.items.find((item) => item.id === itemId) ?? {})) };
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
    state.profileId = event.target.value;
    mandatoryRequirementsAreIncluded();
    invalidateResults();
    renderAll();
  });
  $("#period-input").addEventListener("change", (event) => {
    const raw = Number(event.target.value);
    const value = Math.min(120, Math.max(0.1, Math.round((Number.isFinite(raw) && event.target.value !== "" ? raw : 12) * 10) / 10));
    state.periodMonths = value;
    event.target.value = String(value);
    invalidateResults();
    renderAll();
  });
  $("#requirements-list").addEventListener("change", onRequirementChange);
  $("#toggle-requirements").addEventListener("click", () => {
    const allSelected = state.requirements.every((req) => state.selectedRequirements.has(req.id));
    if (allSelected) state.selectedRequirements = new Set(mandatoryIds());
    else state.selectedRequirements = new Set(state.requirements.map((entry) => entry.id));
    mandatoryRequirementsAreIncluded();
    invalidateResults();
    renderAll();
  });
  $("#catalog-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-toggle-item]");
    if (button) selectItem(button.dataset.toggleItem);
  });
  $("#catalog-list").addEventListener("change", onCostChange);
  $("#catalog-search").addEventListener("input", (event) => {
    state.search = event.target.value;
    renderCatalog();
  });
  $$(".catalog-tab").forEach((tab) => tab.addEventListener("click", () => {
    state.activeKind = tab.dataset.kind;
    $$(".catalog-tab").forEach((other) => other.classList.toggle("is-active", other === tab));
    renderCatalog();
  }));
  $("#clear-selection").addEventListener("click", () => {
    state.candidates.clear();
    invalidateResults();
    renderAll();
    showToast("Выбор очищен.", "success");
  });
  $("#run-evaluation").addEventListener("click", runEvaluation);
  $("#run-optimization").addEventListener("click", runOptimization);
  $("#algorithm-select").addEventListener("change", updateAlgorithmDescription);
  $$('input[name="opt-mode"]').forEach((input) => input.addEventListener("change", updateModeVisibility));
  $("#refresh-data").addEventListener("click", async () => {
    showToast("Обновляем справочники…");
    await loadPageData();
    showToast("Справочники обновлены.", "success");
  });
  $("#notice-close").addEventListener("click", () => { $("#data-notice").hidden = true; });
  $("#mobile-menu").addEventListener("click", () => $(".sidebar").classList.toggle("is-open"));
  $("#logout-button").addEventListener("click", () => { window.location.assign("/"); });
}

async function loadPageData() {
  const result = await workspaceService.loadCatalogs();
  state.requirements = result.requirements;
  state.items = result.items;
  state.profiles = result.profiles;
  state.optimizers = result.optimizers;
  state.usingExamples = result.usingExamples;
  state.serverOnline = result.serverOnline;
  state.problems = result.problems;

  state.profileId = state.profiles.some((entry) => entry.id === state.profileId)
    ? state.profileId
    : (state.profiles[0]?.id ?? "");
  const validRequirementIds = new Set(state.requirements.map((entry) => entry.id));
  state.selectedRequirements = new Set([...state.selectedRequirements].filter((id) => validRequirementIds.has(id)));
  if (!state.initializedOnce) {
    state.selectedRequirements = new Set(mandatoryIds());
  }
  mandatoryRequirementsAreIncluded();
  const validItemIds = new Set(state.items.map((entry) => entry.id));
  for (const itemId of state.candidates.keys()) {
    if (!validItemIds.has(itemId)) state.candidates.delete(itemId);
  }
  state.initializedOnce = true;
  for (const item of state.items) {
    if (!state.prices.has(item.id)) state.prices.set(item.id, { capex: "", opex_month: "" });
  }
  renderOptimizerOptions();
  renderAll();
}

bindEvents();
updateModeVisibility();
loadPageData().catch((error) => {
  state.usingExamples = true;
  state.problems = [error?.message || "Не удалось загрузить справочники"];
  renderApiState();
  showToast("Не удалось загрузить данные. Проверьте соединение с приложением.", "error");
});
