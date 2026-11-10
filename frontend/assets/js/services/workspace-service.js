import { workspaceApi } from "../api/workspace-api.js";
import {
  demoItems,
  demoOptimizers,
  demoProfiles,
  demoRequirements,
} from "../data/workspace-demo-data.js";

async function readArray(label, getter) {
  try {
    const value = await getter();
    if (!Array.isArray(value)) {
      throw new Error(`${label}: сервер вернул данные в неожиданном формате`);
    }
    return { value, ok: true, problem: null };
  } catch (error) {
    return {
      value: [],
      ok: false,
      problem: `${label}: ${error?.status === 501 ? "метод пока не реализован" : error?.message || "данные недоступны"}`,
    };
  }
}

export const workspaceService = Object.freeze({
  async loadCatalogs() {
    const [health, requirements, items, profiles, optimizers] = await Promise.all([
      workspaceApi.health().then(() => true).catch(() => false),
      readArray("Требования", () => workspaceApi.requirements()),
      readArray("Средства и меры", () => workspaceApi.items()),
      readArray("Профили", () => workspaceApi.profiles()),
      readArray("Алгоритмы", () => workspaceApi.optimizers()),
    ]);

    const catalogEntries = [requirements, items, profiles];
    const anyCatalogLoaded = catalogEntries.some((entry) => entry.ok);
    // Демо-набор используется только при полном отсутствии соединения с API.
    // Пустой ответ работающего сервера не подменяем тестовыми записями.
    const usingExamples = !health && !anyCatalogLoaded;
    const pickCatalog = (entry, fallback) => {
      if (entry.ok) return entry.value;
      return usingExamples ? fallback : [];
    };

    const liveRequirements = pickCatalog(requirements, demoRequirements);
    const liveItems = pickCatalog(items, demoItems);
    const liveProfiles = pickCatalog(profiles, demoProfiles);
    const usingExampleOptimizers = !optimizers.ok;
    const liveOptimizers = optimizers.ok ? optimizers.value : demoOptimizers;

    const problems = [requirements, items, profiles, optimizers]
      .filter((entry) => entry.problem)
      .map((entry) => entry.problem);

    return {
      requirements: liveRequirements,
      items: liveItems,
      profiles: liveProfiles,
      optimizers: liveOptimizers,
      usingExamples,
      usingExampleOptimizers,
      serverOnline: health || anyCatalogLoaded,
      catalogsEmpty: !usingExamples && (
        liveRequirements.length === 0 || liveItems.length === 0 || liveProfiles.length === 0
      ),
      problems,
    };
  },

  evaluate(scenario) {
    return workspaceApi.evaluate(scenario);
  },

  optimize(payload) {
    return workspaceApi.optimize(payload);
  },

  pareto(payload) {
    return workspaceApi.pareto(payload);
  },
});
