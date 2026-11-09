import { workspaceApi } from "../api/workspace-api.js";
import {
  demoItems,
  demoOptimizers,
  demoProfiles,
  demoRequirements,
} from "../data/workspace-demo-data.js";

function nonEmptyArray(value) {
  return Array.isArray(value) && value.length > 0;
}

async function getOrExample(label, getter, fallback) {
  try {
    const value = await getter();
    if (!nonEmptyArray(value)) {
      return { value: fallback, example: true, problem: `${label}: справочник пуст` };
    }
    return { value, example: false, problem: null };
  } catch (error) {
    return {
      value: fallback,
      example: true,
      problem: `${label}: ${error?.status === 501 ? "метод пока не реализован" : "данные недоступны"}`,
    };
  }
}

export const workspaceService = Object.freeze({
  async loadCatalogs() {
    const healthPromise = workspaceApi.health().then(() => true).catch(() => false);
    const [requirements, items, profiles, optimizers, serverOnline] = await Promise.all([
      getOrExample("Требования", () => workspaceApi.requirements(), demoRequirements),
      getOrExample("Каталог", () => workspaceApi.items(), demoItems),
      getOrExample("Профили", () => workspaceApi.profiles(), demoProfiles),
      getOrExample("Алгоритмы", () => workspaceApi.optimizers(), demoOptimizers),
      healthPromise,
    ]);

    const entries = [requirements, items, profiles, optimizers];
    const fallbacks = entries.filter((entry) => entry.example);
    const usingExamples = fallbacks.length > 0;
    // Prefer one internally consistent sample dataset over mixing real and sample IDs.
    return {
      requirements: requirements.value,
      items: items.value,
      profiles: profiles.value,
      optimizers: optimizers.value, // у optimizers уже подставлен demoOptimizers при ошибке
      usingExamples: [requirements, items, profiles].some((e) => e.example),
      serverOnline,
      problems: fallbacks.map((entry) => entry.problem),
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
