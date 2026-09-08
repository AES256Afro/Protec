const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function page(value) {
  const elements = new Map();
  const events = new Map();
  let calls = 0;
  const context = vm.createContext({
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, {value: id === 'token' ? value : '', focus() {}, addEventListener(name, handler) { events.set(id + ':' + name, handler); }});
        return elements.get(id);
      },
      querySelectorAll() { return []; }
    },
    fetch: async () => { calls++; return {ok:false,json:async()=>({error:'Administrator authentication required'})}; },
    setInterval() {},
    location: {reload() {}}
  });
  vm.runInContext(fs.readFileSync('static/app.js','utf8'),context);
  return {elements, submit: () => events.get('login-form:submit')({preventDefault() {}}), calls: () => calls};
}

test('masked Unicode and file paths never reach fetch',async () => {
  for (const value of ['•'.repeat(43), '/Users/chris/Projects/Protec/.protec/admin-token', 'abc\r\nHeader: injected']) {
    const fixture = page(value);
    await fixture.submit();
    assert.equal(fixture.calls(),0);
    assert.match(fixture.elements.get('notice').textContent,/Paste the token file contents/);
  }
});

test('token contents with surrounding whitespace reach authentication',async () => {
  const fixture = page('  '+'a'.repeat(43)+'\n');
  await fixture.submit();
  assert.equal(fixture.calls(),1);
  assert.equal(fixture.elements.get('notice').textContent,'Administrator authentication required');
});
