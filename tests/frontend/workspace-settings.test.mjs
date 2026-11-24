import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

const root = new URL('../../frontend/', import.meta.url);
const source = (await readFile(new URL('assets/js/pages/workspace-page.js', root), 'utf8'))
  .replace(/^import .*;\r?\n/gm, '').split('initialize().catch')[0];

function workspace(service = {}) {
  const nodes = new Map();
  const node = (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, {
      innerHTML: '', textContent: '', value: '', checked: false, dataset: {},
      hidden: false, disabled: false, querySelector: node, querySelectorAll: () => [],
      classList: { add() {}, remove() {}, toggle() {} }, style: { setProperty() {} }, focus() {},
    });
    return nodes.get(selector);
  };
  const saved = [];
  const context = createContext({
    document: { querySelector: node, querySelectorAll: () => [] },
    window: { scrollTo() {}, dispatchEvent() {} },
    workspaceService: service, AbortController, CustomEvent: class {},
    apiRequest: async (path, request) => { saved.push(request.body); },
  });
  runInContext(source, context);
  runInContext('showToast = () => {};', context);
  node("input[name='opt-mode']:checked").value = 'min_cost';
  return { node, saved, run: (code) => runInContext(code, context) };
}

test('manual mandatory settings preserve the profile and survive draft saving', async () => {
  const page = workspace();
  page.run(`
    state.requirements = [{id:'R1',title:'First'}, {id:'R2',title:'Second'}];
    requirementsById = new Map(state.requirements.map(row=>[row.id,row]));
    state.profiles = [{id:'K1',mandatory:['R1']}]; state.profileId='K1';
    state.selectedRequirements = new Set(['R1']);
    renderAll = () => {}; invalidateResults = () => {};
    setRequirementMandatory('R1', false); setRequirementMandatory('R2', true);
  `);
  assert.deepEqual(Array.from(page.run('mandatoryIds()')), ['R2']);
  assert.deepEqual(Array.from(page.run('state.profiles[0].mandatory')), ['R1']);
  assert.ok(page.run("state.selectedRequirements.has('R2')"));
  page.run(`draftPath='/users/1/draft';state.initializedOnce=true;state.usingExamples=false;queueDraftSave();`);
  await page.run('draftSave');
  assert.deepEqual(Array.from(page.saved[0].mandatory), ['R2']);
  const snapshot = JSON.stringify(page.saved[0]);
  page.run(`restoreDraft(${snapshot});`);
  assert.deepEqual(Array.from(page.run('scenarioFor().mandatory')), ['R2']);
  page.run('state.mandatoryOverride = new Set();');
  assert.deepEqual(Array.from(page.run('scenarioFor().mandatory')), []);
  page.run('state.mandatoryOverride = null;');
  assert.deepEqual(Array.from(page.run('mandatoryIds()')), ['R1']);
});

test('compromise has its own compatible algorithm and optional budget', () => {
  const page = workspace();
  page.run(`state.optimizers=[{name:'boolean-ilp',title:'Exact'}, {name:'multiobjective',title:'Compromise'}];`);
  page.run('renderOptimizerOptions();');
  assert.doesNotMatch(page.node('#algorithm-select').innerHTML, /multiobjective/);
  page.node("input[name='opt-mode']:checked").value = 'compromise';
  page.run('updateModeVisibility();');
  assert.match(page.node('#algorithm-select').innerHTML, /multiobjective/);
  assert.doesNotMatch(page.node('#algorithm-select').innerHTML, /boolean-ilp/);
  assert.equal(page.run('optimizationParameters().budget'), null);
  page.node('#compromise-use-budget').checked = true;
  page.node('#budget-input').value = '10';
  assert.equal(page.run('optimizationParameters().budget'), 10);
});

test('a server search limit is reported without running an approximate replacement', async () => {
  const page = workspace({ async optimize() { throw Object.assign(new Error('Limit'), {status:422}); } });
  await page.run(`
    state.selectedRequirements=new Set(['R']);
    state.items=[{id:'A',name:'A',covers:['R']}]; itemsById=new Map([['A',state.items[0]]]);
    state.candidates.set('A',{capex:1,opex_month:0,implement_days:1});
    state.usingExamples=false;
    localOptimize = () => { throw new Error('Approximate fallback must not run'); };
    runOptimization();
  `);
  assert.equal(page.run('state.isCalculating'), false);
  assert.equal(page.run('state.lastOptimization'), null);
  assert.equal(page.node('#run-optimization').disabled, false);
});

test('workspace local assets exist', async () => {
  const html = await readFile(new URL('workspace.html', root), 'utf8');
  for (const match of html.matchAll(/(?:href|src)="\/static\/([^"?]+)(?:\?[^\"]*)?"/g)) {
    await readFile(new URL(match[1], root));
  }
});
