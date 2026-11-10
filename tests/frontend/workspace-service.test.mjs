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

function setApi({ requirements, items, profiles, optimizers, online = true }) {
  globalThis.testWorkspaceApi = {
    health: online ? async () => ({ status: 'ok' }) : async () => { throw new Error('offline'); },
    requirements: requirements ?? (async () => [{ id: 'real-req' }]),
    items: items ?? (async () => [{ id: 'real-item', covers: ['real-req'] }]),
    profiles: profiles ?? (async () => [{ id: 'real-profile', mandatory: ['real-req'] }]),
    optimizers: optimizers ?? (async () => [{ name: 'real-optimizer' }]),
  };
}

async function loadService(suffix) {
  const url = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}#${suffix}`;
  return import(url);
}

test('uses real requirements, measures and profiles returned by the API', async () => {
  setApi({});
  const { workspaceService } = await loadService('live-catalog');
  const result = await workspaceService.loadCatalogs();
  assert.equal(result.usingExamples, false);
  assert.equal(result.catalogsEmpty, false);
  assert.deepEqual(result.requirements, [{ id: 'real-req' }]);
  assert.deepEqual(result.items, [{ id: 'real-item', covers: ['real-req'] }]);
  assert.deepEqual(result.profiles, [{ id: 'real-profile', mandatory: ['real-req'] }]);
});

for (const missing of ['requirements', 'items', 'profiles']) {
  test(`keeps an empty live ${missing} catalogue empty instead of substituting demo rows`, async () => {
    setApi({ [missing]: async () => [] });
    const { workspaceService } = await loadService(`empty-${missing}`);
    const result = await workspaceService.loadCatalogs();
    assert.equal(result.usingExamples, false);
    assert.equal(result.catalogsEmpty, true);
    assert.deepEqual(result[missing], []);
  });
}

test('uses a consistent demo dataset only when the API is offline', async () => {
  const offline = async () => { throw new Error('offline'); };
  setApi({ requirements: offline, items: offline, profiles: offline, optimizers: offline, online: false });
  const { workspaceService } = await loadService('offline');
  const result = await workspaceService.loadCatalogs();
  assert.equal(result.usingExamples, true);
  const ids = new Set(result.requirements.map((r) => r.id));
  assert.ok(result.profiles.every((p) => p.mandatory.every((id) => ids.has(id))));
  assert.ok(result.items.every((item) => item.covers.every((id) => ids.has(id))));
});

test('keeps live catalogues when the optimizers endpoint is not implemented', async () => {
  setApi({ optimizers: async () => { const error = new Error('Not implemented'); error.status = 501; throw error; } });
  const { workspaceService } = await loadService('no-optimizers');
  const result = await workspaceService.loadCatalogs();
  assert.equal(result.usingExamples, false);
  assert.equal(result.usingExampleOptimizers, true);
  assert.deepEqual(result.requirements, [{ id: 'real-req' }]);
});
