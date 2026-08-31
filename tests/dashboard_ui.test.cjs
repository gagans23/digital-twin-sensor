const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

async function dashboard() {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      innerHTML: '', value: '', listeners: {}, dataset: {},
      classList: { add() {}, remove() {}, toggle() {} },
      addEventListener(name, callback) { this.listeners[name] = callback; },
    });
    return elements.get(id);
  }
  const context = vm.createContext({
    document: {
      getElementById: element, querySelectorAll: () => [],
      querySelector: () => ({ content: 'synthetic-session-token' }),
    },
    window: { location: { hash: '' }, addEventListener() {}, clearTimeout() {}, setTimeout() {} },
    fetch: async () => ({ ok: false, status: 503, json: async () => ({ error: 'synthetic bootstrap' }) }),
  });
  vm.runInContext(readFileSync(path.join(__dirname, '../digital_twin_sensor/ui_static/app.js'), 'utf8'), context);
  await new Promise(setImmediate);
  return { context, element };
}

test('fleet and privacy connector renderers remain separate', async () => {
  const { context, element } = await dashboard();
  context.renderFleetConnectors([]);
  context.renderConnectors([], {});
  assert.match(element('connectorList').innerHTML, /No items yet/);
  assert.match(element('connectorActivity').innerHTML, /No structured captures/);
});

test('restriction resolution needs confirmation and supports cancellation', async () => {
  const { context, element } = await dashboard();
  const handler = element('recentFeedback').listeners.click;
  const confirmation = { hidden: true };
  const request = { hidden: false, nextElementSibling: confirmation };
  confirmation.previousElementSibling = request;
  const target = (selector, button) => ({ closest: value => value === selector ? button : null });
  const calls = [];
  context.fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ resolved: true }) };
  };
  context.refresh = async () => {};
  await handler({ target: target('button[data-request-resolution]', request) });
  assert.equal(confirmation.hidden, false);
  assert.equal(calls.length, 0);
  await handler({ target: target('button[data-cancel-resolution]', { parentElement: confirmation }) });
  assert.equal(confirmation.hidden, true);
  assert.equal(request.hidden, false);
  assert.equal(calls.length, 0);
  await handler({ target: target('button[data-request-resolution]', request) });
  await handler({ target: target('button[data-resolve-feedback]', { dataset: { resolveFeedback: '7' } }) });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/feedback/resolve');
  assert.equal(calls[0].options.headers['X-DTS-Token'], 'synthetic-session-token');
  assert.deepEqual(JSON.parse(calls[0].options.body), { feedback_id: 7 });
});

test('restrictive feedback rebuilds the visible pack immediately', async () => {
  const { context } = await dashboard();
  vm.runInContext("state.contextPack = {pack_id:'pack_synthetic', selected_sphere_id:'sphere_synthetic', status:'ready'}", context);
  context.postJson = async () => ({});
  context.getJson = async () => ({});
  context.renderLearning = () => {};
  let rebuilds = 0;
  context.buildContextPack = async () => { rebuilds++; };
  for (const label of ['too_private', 'wrong', 'stale']) await context.submitLearningFeedback(label);
  assert.equal(rebuilds, 3);
});

test('blocked summary explains the restriction, not target allowlisting', async () => {
  const { context, element } = await dashboard();
  context.renderPackSummary({ status: 'blocked', selection_reason: 'Review required', admission: { target_reason: 'Target allowed' } });
  assert.match(element('packSummary').innerHTML, /Review required/);
  assert.doesNotMatch(element('packSummary').innerHTML, /Target allowed/);
});

function resumeView() {
  return {
    status: 'ready', selected_sphere_id: 'synthetic-sphere', title: 'Synthetic task',
    tasks: [{ id: 'synthetic-sphere', title: 'Synthetic task' }], coverage: {state:'recent'},
    checkpoint: {id:1,state:'Confirmed state',next_step:'Saved step',question:'Open question',confirmed_at:'2026-08-31T10:00:00Z'},
    history: [], observations: [], sessions: [],
  };
}

test('refresh preserves a checkpoint draft and its original revision', async () => {
  const { context, element } = await dashboard();
  context.renderResume(resumeView());
  element('resumeNext').value = 'Unsaved draft';
  element('resumeCheckpointForm').listeners.input();
  const newer = resumeView();
  newer.checkpoint.id = 2;
  context.renderResume(newer);
  assert.equal(element('resumeNext').value, 'Unsaved draft');
  assert.equal(vm.runInContext('state.resumeBaseCheckpointId', context), 1);
  assert.equal(element('resumeTask').disabled, true);
  assert.equal(element('daysSelect').disabled, true);
});

test('a blocked resume clears old checkpoint text and disables actions', async () => {
  const { context, element } = await dashboard();
  context.renderResume(resumeView());
  context.renderResume({ status: 'blocked', selected_sphere_id: 'synthetic-sphere', tasks: [], coverage: {}, reason: 'Review required' });
  assert.equal(element('resumeState').value, '');
  assert.equal(element('resumeFields').disabled, true);
  assert.equal(element('resumeStart').disabled, true);
  assert.doesNotMatch(element('resumeConfirmed').innerHTML, /Confirmed state/);
});

test('resume text is escaped and is not rendered as markup', async () => {
  const { context, element } = await dashboard();
  const view = resumeView();
  view.checkpoint.state = '<img src=x onerror=alert(1)>';
  context.renderResume(view);
  assert.match(element('resumeConfirmed').innerHTML, /&lt;img/);
  assert.doesNotMatch(element('resumeConfirmed').innerHTML, /<img/);
});
