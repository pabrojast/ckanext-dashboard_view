import test from 'node:test';
import assert from 'node:assert/strict';
import { storyState, connectStoryBridge } from '../src/storyBridge.ts';

const profile = {fields: [{key: 'country', type: 'text'}, {key: 'value', type: 'number'}]};
const config = {widgets: [{id: 'chart-1', title: 'Observations', type: 'bar'}], filters: []};
test('validates declarative filters and chart references', () => {
  const state = {filters: [{field: 'value', op: 'between', value: [1, 4]}], widgetId: 'chart-1'};
  assert.deepEqual(storyState(state, profile, config), state);
  assert.throws(() => storyState({...state, widgetId: 'deleted'}, profile, config));
  assert.throws(() => storyState({filters: [{field: 'secret', op: 'eq', value: 'x'}]}, profile, config));
  assert.throws(() => storyState({filters: [{field: 'value', op: 'between', value: [1]}]}, profile, config));
  assert.throws(() => storyState({filters: [{field: 'country', op: 'eq', value: {script: 'x'}}]}, profile, config));
});
test('accepts only the same-origin parent and correlates superseded responses', async () => {
  const messages = [], work = [];
  let receive;
  globalThis.window = {location: {origin: 'https://portal.test'},
    parent: {postMessage: data => messages.push(data)},
    addEventListener: (_, callback) => {receive = callback;}};
  const ready = connectStoryBridge({viewId: 'view', signal: new AbortController().signal,
    metadata: () => ({profile, config}), apply: () => new Promise(resolve => work.push(resolve))});
  ready();
  assert.equal(messages[0].type, 'dashboard:ready');
  const event = requestId => ({origin: window.location.origin, source: window.parent,
    data: {version: 1, viewId: 'view', type: 'dashboard:applyState', requestId, state: {filters: []}}});
  await receive({...event('bad'), origin: 'https://other.test'});
  await receive({...event('bad'), source: {}});
  assert.equal(work.length, 0);
  const first = receive(event('one')), second = receive(event('two'));
  work[1](true); await second; work[0](false); await first;
  assert.equal(messages.find(m => m.requestId === 'two' && m.phase === 'complete').superseded, false);
  assert.equal(messages.find(m => m.requestId === 'one' && m.phase === 'complete').superseded, true);
  delete globalThis.window;
});
