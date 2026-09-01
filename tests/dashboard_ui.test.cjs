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

test('observability separates local logging from Opik acceptance', async () => {
  const { context, element } = await dashboard();
  context.renderObservability({mode:'local', records:1, pending:0, exporter:{}, recent:[]});
  assert.equal(element('obsEnabled').checked, true);
  assert.match(element('obsNotice').textContent, /Nothing is being sent/);
  assert.equal(element('obsAccepted').textContent, 'Never');
  assert.equal(element('obsOpen').hidden, true);
  context.renderObservability({mode:'opik', destination:'https://example.com/api', pending:2, exporter:{last_error:'authentication'}, recent:[]});
  assert.equal(element('obsError').textContent, 'authentication');
  assert.equal(element('obsPending').textContent, '2');
  assert.equal(element('obsAccepted').textContent, 'Never');
});

test('observability escapes trace text and filters nested blocked outcomes', async () => {
  const { context, element } = await dashboard();
  const trace = {id:'synthetic', name:'<script>unsafe</script>', start:1, duration_ms:10, outcome:'ok', error:'none', delivery:'local', counts:{},
    spans:[{name:'context.pack', outcome:'blocked', duration_ms:1, error:'none'}]};
  context.renderObservability({mode:'local', recent:[trace], exporter:{}});
  assert.doesNotMatch(element('obsTraces').innerHTML, /<script>/);
  element('obsFilter').value = 'blocked';
  context.renderOperationalTraces();
  assert.match(element('obsTraces').innerHTML, /context.pack/);
  element('obsFilter').value = 'error';
  context.renderOperationalTraces();
  assert.match(element('obsTraces').innerHTML, /No matching outcomes/);
});

test('observability pause posts only a local action and purge needs confirmation', async () => {
  const { context, element } = await dashboard();
  const calls = [];
  context.postJson = async (url, payload) => {calls.push({url, payload}); return {mode:'off', recent:[], exporter:{}};};
  await element('obsEnabled').listeners.change({target:{checked:false}});
  assert.equal(calls[0].payload.action, 'off');
  element('obsClear').listeners.click();
  assert.equal(element('obsClearConfirm').hidden, false);
  assert.equal(calls.length, 1);
  element('obsClearNo').listeners.click();
  assert.equal(calls.length, 1);
  await element('obsClearYes').listeners.click();
  assert.equal(calls[1].payload.action, 'purge');
});

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
    history: [], observations: [], sessions: [], identity: null, saved_tasks: [],
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

test('task identity names are escaped and drafts block navigation', async () => {
  const { context, element } = await dashboard();
  const view = resumeView();
  view.identity = {id:'saved-1', name:'<img src=x>', revision:3, aliases:['synthetic-sphere'], restricted:false};
  view.saved_tasks = [view.identity];
  context.renderResume(view);
  assert.equal(element('taskIdentityName').value, '<img src=x>');
  assert.doesNotMatch(element('resumeTask').innerHTML, /<img/);
  element('taskIdentityName').value = 'Human task name';
  element('taskIdentityName').listeners.input();
  assert.equal(element('resumeTask').disabled, true);
  assert.equal(element('daysSelect').disabled, true);
  assert.equal(element('taskIdentityDiscard').hidden, false);
});

test('link and unlink require explicit UI actions and revision tokens', async () => {
  const { context, element } = await dashboard();
  const calls = [];
  const view = resumeView();
  view.saved_tasks = [{id:'saved-1', name:'Saved task', revision:4, aliases:['other'], restricted:false}];
  context.postJson = async (url, payload) => { calls.push({url, payload}); return {}; };
  context.loadResume = async () => {};
  context.renderResume(view);
  element('taskIdentityTarget').value = 'saved-1';
  element('taskIdentityTarget').listeners.change();
  await element('taskIdentityLink').listeners.click();
  assert.equal(calls[0].payload.action, 'link_task');
  assert.equal(calls[0].payload.target_revision, 4);
  assert.equal(calls[0].payload.identity_revision, null);

  view.identity = {id:'saved-1', name:'Saved task', revision:5, aliases:['synthetic-sphere','other'], restricted:false};
  context.renderResume(view);
  element('taskIdentityUnlink').listeners.click();
  assert.equal(element('taskIdentityConfirm').hidden, false);
  assert.equal(calls.length, 1);
  await element('taskIdentityUnlinkYes').listeners.click();
  assert.equal(calls[1].payload.action, 'unlink_task');
  assert.equal(calls[1].payload.identity_revision, 5);
});
