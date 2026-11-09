import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../../frontend/assets/js/', import.meta.url);
const demoSource = await readFile(new URL('data/workspace-demo-data.js', root), 'utf8');
const serviceSource = await readFile(new URL('services/workspace-service.js', root), 'utf8');
const demoUrl = `data:text/javascript;base64,${Buffer.from(demoSource).toString('base64')}`;
const source = serviceSource
  .replace('import { workspaceApi } from "../api/workspace-api.js";', 'const workspaceApi = globalThis.testWorkspaceApi;')
  .replace('"../data/workspace-demo-data.js"', JSON.stringify(demoUrl));

for (const missing of ['requirements', 'items', 'profiles', 'optimizers', null]) {
  test(`catalog consistency when ${missing ?? 'nothing'} is unavailable`, async () => {
    const real = {
      requirements: [{ id: 'real-req' }],
      items: [{ id: 'real-item', covers: ['real-req'] }],
      profiles: [{ id: 'real-profile', mandatory: ['real-req'] }],
      optimizers: [{ name: 'real-optimizer' }],
    };
    globalThis.testWorkspaceApi = Object.fromEntries(Object.entries(real).map(
      ([key, value]) => [key, async () => key === missing ? [] : value],
    ));
    globalThis.testWorkspaceApi.health = async () => ({});
    const url = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}#${missing}`;
    const { workspaceService } = await import(url);
    const result = await workspaceService.loadCatalogs();
    const usesDemo = missing !== null && missing !== 'optimizers';
    assert.equal(result.usingExamples, usesDemo);
    const ids = new Set(result.requirements.map((r) => r.id));
    assert.ok(result.profiles.every((p) => p.mandatory.every((id) => ids.has(id))));
    assert.ok(result.items.every((item) => item.covers.every((id) => ids.has(id))));
    if (!usesDemo) {
      assert.deepEqual(result.requirements, real.requirements);
      assert.deepEqual(result.items, real.items);
      assert.deepEqual(result.profiles, real.profiles);
    }
  });
}
