const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/templates/real_test_panel.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1]
  .replace('{{ cases_json|safe }}', '[]')
  .replace('{{ summary_json|safe }}', '{}')
  .replace(/init\(\);\s*$/, '');
const attack = '<img src=x onerror="globalThis.injected=true">';

class Element {
  constructor(tagName = 'div', id = '') {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.value = '';
    this.disabled = false;
    this.checked = false;
    this.hidden = false;
    this.style = {};
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this._text = '';
    this._html = '';
    this.classes = new Set();
    this.classList = {
      add: (...names) => names.forEach(name => this.classes.add(name)),
      remove: (...names) => names.forEach(name => this.classes.delete(name)),
      contains: name => this.classes.has(name),
      toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name),
    };
  }
  set textContent(value) { this._text = String(value); this._html = ''; this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set innerHTML(value) {
    assert.ok(!String(value).includes(attack), 'untrusted content must not enter innerHTML');
    assert.ok(!this.id.startsWith('qianniu'), 'preview containers must use textContent');
    this._html = String(value); this._text = ''; this.children = [];
  }
  get innerHTML() { return this._html; }
  appendChild(child) { this.children.push(child); return child; }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  replaceChildren(...children) { this._text = ''; this._html = ''; this.children = children; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  focus() {}
}

function harness() {
  const elements = new Map();
  for (const match of html.matchAll(/<([\w-]+)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const el = new Element(match[1], match[2]);
    for (const attr of match[0].matchAll(/([\w-]+)="([^"]*)"/g)) el.attributes[attr[1]] = attr[2];
    el.value = el.attributes.value || '';
    elements.set(el.id, el);
  }
  const requests = [], storageWrites = [], documentListeners = {};
  const document = {
    body: new Element('body', 'body'),
    getElementById: id => elements.get(id) || null,
    createElement: tag => new Element(tag),
    querySelector: () => null,
    querySelectorAll: () => [...elements.values()].filter(el => el.classList.contains('open')),
    addEventListener: (name, fn) => (documentListeners[name] ||= []).push(fn),
  };
  const context = vm.createContext({
    document, AbortController, performance: {now: () => 0},
    localStorage: {getItem: () => null, setItem: (key, value) => storageWrites.push({key, value})},
    setTimeout: () => 1, clearTimeout() {}, navigator: {}, window: {},
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject})),
    alert: message => assert.fail(`unexpected alert: ${message}`),
  });
  vm.runInContext(script, context);
  const evaluate = code => vm.runInContext(code, context);
  const el = id => { assert.ok(elements.has(id), `missing frontend control: ${id}`); return elements.get(id); };
  const snapshot = code => JSON.parse(JSON.stringify(evaluate(code)));
  const requireImport = () => assert.equal(evaluate('typeof readCurrentQianniuConversation'), 'function', 'manual preview entry point is missing');
  const begin = () => { requireImport(); return evaluate('readCurrentQianniuConversation()'); };
  const respond = (index, body, status = 200) => requests[index].resolve({ok: status >= 200 && status < 300, status, json: async () => body});
  const ready = async (body = preview()) => { const pending = begin(); respond(requests.length - 1, body); await pending; };
  const choose = value => { el('qianniuOrderChoice').value = value; evaluate('qianniuOrderChanged()'); };
  const confirm = () => evaluate('confirmQianniuImport()');
  return {elements, documentListeners, evaluate, el, snapshot, requests, storageWrites, begin, respond, ready, choose, confirm};
}

function preview(historyCount = 4) {
  return {
    ok: true, status: 'preview_ready', conversation_ref: 'opaque-conversation-ref', shop_name: 'Preview shop',
    diagnostics: {turn_count: historyCount + 1, history_scope: 'visible_conversation_document'},
    window: {handle: 42, label: 'QianNiu reception'},
    context: {
      customer_message: 'Current buyer question', can_send: false, requires_human_review: true,
      conversation_history: Array.from({length: historyCount}, (_, i) => ({
        role: i % 2 ? 'agent' : 'customer', content: `message ${i}`, turn_index: i,
        timestamp: '2026-09-09 10:00:00', turn_uid: `turn-${i}`,
      })),
      order_candidates: [{value: 'order-A', verified: false, source: 'uia_order_card'}],
      product_candidates: [{value: 'product-code', verified: false, source: 'uia_product_code'}],
    },
  };
}

function assistedPreview() {
  const data = preview(3);
  data.status = 'manual_confirmation_required';
  data.buyer_name = 'Fixture buyer';
  data.diagnostics.current_customer_binding_verified = false;
  data.diagnostics.mode = 'manual_document_review';
  data.diagnostics.turn_count = 3;
  data.context.source = 'qianniu_manual_document';
  data.context.customer_message = '';
  data.context.order_candidates = [];
  data.context.product_candidates = [];
  return data;
}

async function assistedReady(h, data = assistedPreview()) {
  const pending = h.evaluate("readCurrentQianniuConversation(undefined, 'manual_document_review')");
  h.respond(h.requests.length - 1, data);
  await pending;
}

test('assisted import requires explicit mode, matching human inputs and acknowledgment', async () => {
  const h = harness();
  assert.match(h.el('qianniuAssistedButton').attributes.onclick, /manual_document_review/);
  h.el('message').value = 'OLD';
  h.el('orderId').value = 'OLD';
  await assistedReady(h);
  assert.deepEqual(JSON.parse(h.requests[0].options.body), {mode: 'manual_document_review'});
  assert.equal(h.el('qianniuBuyerConfirm').value, '');
  assert.equal(h.el('qianniuShopConfirm').value, '');
  assert.equal(h.el('qianniuDocumentConfirmed').checked, false);
  h.choose('none'); h.confirm();
  assert.equal(h.el('message').value, 'OLD');
  h.el('qianniuBuyerConfirm').value = 'Fixture buyer';
  h.el('qianniuShopConfirm').value = 'WRONG';
  h.el('qianniuDocumentConfirmed').checked = true;
  h.choose('none');
  assert.equal(h.el('qianniuConfirmButton').disabled, true);
  h.el('qianniuShopConfirm').value = 'Preview shop';
  h.el('qianniuDocumentConfirmed').checked = false;
  h.choose('none');
  assert.equal(h.el('qianniuConfirmButton').disabled, true);
  h.el('qianniuDocumentConfirmed').checked = true;
  h.choose('none');
  assert.equal(h.el('qianniuConfirmButton').disabled, false);
  h.confirm();
  assert.equal(h.el('message').value, '');
  assert.equal(h.el('orderId').value, '');
  assert.equal(h.snapshot('parsedConversation.history').length, 3);
  assert.equal(h.snapshot('parsedConversation.source'), 'qianniu_manual_document');
  h.el('message').value = 'Manually entered current question';
  const payload = h.snapshot('buildPayload()');
  assert.equal(payload.message, 'Manually entered current question');
  assert.equal(payload.copilot_context.conversation_history.length, 3);
  assert.ok(!JSON.stringify(payload).includes('Fixture buyer'));
  assert.ok(!JSON.stringify(h.storageWrites).includes('Fixture buyer'));
  assert.equal(h.requests.length, 1, 'import never calls Agent or submits identity');
  assert.equal(h.el('qianniuBuyerConfirm').value, '');
  assert.equal(h.el('qianniuDocumentConfirmed').checked, false);
});

test('assisted window choice retains explicit mode and still waits for selection', async () => {
  const h = harness();
  const pending = h.evaluate("readCurrentQianniuConversation(undefined, 'manual_document_review')");
  h.respond(0, {status:'window_selection_required', windows:[{handle:42,label:'Fixture'}]});
  await pending;
  assert.equal(h.el('qianniuWindowReadButton').disabled, true);
  h.el('qianniuWindowChoice').value = '0';
  const capture = h.evaluate('captureSelectedQianniuWindow()');
  assert.deepEqual(JSON.parse(h.requests[1].options.body), {window_handle:42,mode:'manual_document_review'});
  h.respond(1, assistedPreview());
  await capture;
  assert.equal(h.el('qianniuHumanConfirmation').hidden, false);
});

test('assisted preview rejects authority, order, current question and mode substitutions', async () => {
  for (const mutate of [
    d => d.diagnostics.current_customer_binding_verified = true,
    d => delete d.buyer_name,
    d => d.context.order_candidates = preview().context.order_candidates,
    d => d.context.product_candidates = preview().context.product_candidates,
    d => d.context.customer_message = 'Do not promote old question',
    d => d.context.source = 'qianniu_uia_preview',
    d => d.status = 'preview_ready',
  ]) {
    const h = harness(), data = assistedPreview();
    mutate(data); await assistedReady(h, data);
    assert.equal(h.evaluate('qianniuPreview'), null);
    assert.equal(h.el('qianniuConfirmButton').disabled, true);
  }
  const h = harness();
  await h.ready(assistedPreview());
  assert.equal(h.evaluate('qianniuPreview'), null, 'native mode must not fall back to assisted');
});

test('assisted identity labels render inertly and disappear on cancel or mode switch', async () => {
  const h = harness(), data = assistedPreview();
  data.buyer_name = attack;
  await assistedReady(h, data);
  assert.ok(h.el('qianniuBuyer').textContent.includes(attack));
  h.el('qianniuBuyerConfirm').value = attack;
  h.el('qianniuDocumentConfirmed').checked = true;
  h.evaluate('cancelQianniuPreview()');
  assert.equal(h.el('qianniuBuyer').textContent, '');
  assert.equal(h.el('qianniuBuyerConfirm').value, '');
  assert.equal(h.el('qianniuDocumentConfirmed').checked, false);
  await h.ready();
  assert.equal(h.el('qianniuHumanConfirmation').hidden, true);
  assert.equal(h.evaluate('globalThis.injected'), undefined);
});

test('manual entry is wired near history import and never captures on initialization', () => {
  const h = harness();
  assert.match(h.el('qianniuReadButton').attributes.onclick, /readCurrentQianniuConversation\(\)/);
  h.evaluate('init()');
  assert.equal(h.requests.length, 0);
});

test('preview is a separate POST and cannot import or analyze without order choice and confirmation', async () => {
  const h = harness();
  h.el('message').value = 'previous buyer';
  await h.ready();
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, '/ask/api/sidecar/qianniu/preview');
  assert.equal(h.requests[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(h.requests[0].options.body), {});
  assert.equal(h.requests[0].options.credentials, 'same-origin');
  assert.equal(h.requests[0].options.cache, 'no-store');
  assert.equal(h.el('message').value, 'previous buyer');
  assert.equal(h.el('qianniuOrderChoice').value, '');
  assert.equal(h.el('qianniuConfirmButton').disabled, true);
  h.confirm();
  assert.equal(h.el('message').value, 'previous buyer');
  h.choose('0');
  assert.equal(h.el('qianniuConfirmButton').disabled, false);
  h.confirm();
  assert.equal(h.el('orderId').value, 'order-A');
  assert.equal(h.el('message').value, 'Current buyer question');
  assert.equal(h.requests.length, 1, 'confirmation must not generate or post context');
  const id = h.evaluate('currentConversationId');
  h.confirm();
  assert.equal(h.evaluate('currentConversationId'), id, 'double confirmation must be a no-op');
  assert.ok(h.storageWrites.every(write => write.key === 'inhe_real_test_conversation_id_v1'));
  assert.ok(h.storageWrites.every(write => !write.value.includes('Current buyer question')));
});

test('window selection posts exactly the explicitly chosen numeric handle, not the first', async () => {
  const h = harness();
  const pending = h.begin();
  h.respond(0, {status: 'window_selection_required', windows: [{handle: 11, label: attack}, {handle: 42, label: 'Second'}]});
  await pending;
  assert.equal(h.el('qianniuWindowChoice').value, '');
  assert.equal(h.el('qianniuWindowReadButton').disabled, true);
  h.evaluate('captureSelectedQianniuWindow()');
  assert.equal(h.requests.length, 1);
  h.el('qianniuWindowChoice').value = '1';
  h.evaluate('qianniuWindowChanged()');
  const capture = h.evaluate('captureSelectedQianniuWindow()');
  assert.deepEqual(JSON.parse(h.requests[1].options.body), {window_handle: 42});
  h.respond(1, preview());
  await capture;
  assert.equal(h.el('qianniuConfirmButton').disabled, true);
});

test('explicit no-order choice remains available with zero or multiple candidates', async () => {
  for (const orders of [[], preview().context.order_candidates.concat({value: 'order-B', verified: false, source: 'uia_order_card'})]) {
    const h = harness(), data = preview();
    data.context.order_candidates = orders;
    h.el('orderId').value = 'old-order';
    await h.ready(data);
    h.confirm();
    assert.equal(h.el('orderId').value, 'old-order');
    h.choose('none'); h.confirm();
    assert.equal(h.el('orderId').value, '');
    assert.equal(h.snapshot('buildPayload()').order_id, undefined);
  }
});

test('import preserves all canonical turns and metadata through previews and raw parse hooks', async () => {
  const h = harness(), data = preview(41);
  data.context.conversation_history[0].content = 'agent: body text is not a role\ncustomer: still the same turn';
  await h.ready(data);
  assert.equal(h.el('qianniuMessages').children.length, 42);
  assert.match(h.el('qianniuScope').textContent, /可见|视口/);
  assert.match(h.el('qianniuScope').textContent, /未确认完整历史|不代表完整聊天历史/);
  h.choose('none'); h.confirm();
  h.evaluate('fillPayloadPreview(); parseRawContext(false); parseRawContext(true);');
  const payload = h.snapshot('buildPayload()');
  assert.deepEqual(payload.copilot_context.conversation_history, data.context.conversation_history);
  assert.equal(payload.message, data.context.customer_message);
  assert.equal(payload.copilot_context.raw_chat_context, undefined);
  assert.equal(h.el('rawContext').value, '');
  assert.match(h.el('parsedContextPreview').innerHTML, /客服/);
});

test('raw text, shop, window labels and unverified candidate labels render as inert text', async () => {
  const h = harness(), data = preview();
  data.shop_name = attack; data.window.label = attack;
  data.context.customer_message = attack;
  data.context.conversation_history[0].content = attack;
  data.context.order_candidates[0].value = attack;
  data.context.order_candidates[0].source = attack;
  data.context.product_candidates[0].value = attack;
  data.context.product_candidates[0].source = attack;
  await h.ready(data);
  assert.ok(h.el('qianniuMessages').textContent.includes(attack));
  assert.ok(h.el('qianniuOrderChoice').textContent.includes(attack));
  assert.match(h.el('qianniuOrderChoice').textContent, /未核验/);
  assert.ok(h.el('qianniuProducts').textContent.includes(attack));
  assert.match(h.el('qianniuProducts').textContent, /商品编号|非 SKU/);
  h.choose('0'); h.confirm();
  assert.equal(h.el('message').value, attack);
  assert.equal(h.el('shopName').value, attack);
  assert.equal(h.el('sku').value, '');
  assert.deepEqual(h.snapshot('buildPayload().product_candidates || []'), []);
  assert.equal(h.evaluate('globalThis.injected'), undefined);
});

test('import clears previous buyer identity, attachments, candidate state, review and stale reply', async () => {
  const h = harness();
  for (const id of ['message', 'shopName', 'frontTitle', 'sku', 'orderId', 'imageKind', 'imageDescription', 'finalReply', 'reviewNote']) h.el(id).value = 'OLD';
  h.el('candidates').value = '[{"value":"OLD","type":"sku_id_candidate"}]';
  h.el('imageCount').value = '2';
  h.el('rawContext').value = 'customer: OLD';
  h.evaluate('parseRawContext(false); currentImages=[{data_url:"OLD"}]; lastResponse={suggested_reply:"OLD"}; lastSubmittedPayload={message:"OLD"};');
  h.el('decisionShadowPreviewBody').textContent = 'OLD';
  h.el('rawBox').textContent = 'OLD';
  h.el('mediaSuggestBody').textContent = 'OLD';
  await h.ready(); h.choose('none'); h.confirm();
  const payload = h.snapshot('buildPayload()');
  assert.ok(!JSON.stringify(payload).includes('OLD'));
  assert.equal(payload.image_attachments, undefined);
  assert.equal(h.evaluate('lastResponse'), null);
  assert.equal(h.evaluate('lastSubmittedPayload'), null);
  for (const id of ['frontTitle', 'sku', 'imageKind', 'imageDescription', 'finalReply', 'reviewNote']) assert.equal(h.el(id).value, '');
  for (const id of ['decisionShadowPreviewBody', 'rawBox', 'mediaSuggestBody']) assert.equal(h.el(id).textContent, '');
});

test('new buyer hook clears canonical and legacy context even before an import', () => {
  const h = harness();
  h.el('message').value = 'OLD'; h.el('sku').value = 'OLD';
  h.el('rawContext').value = 'customer: OLD'; h.evaluate('parseRawContext(false); newConversation();');
  assert.equal(h.el('message').value, '');
  assert.equal(h.el('sku').value, '');
  assert.equal(h.el('rawContext').value, '');
  assert.deepEqual(h.snapshot('parsedConversation.history'), []);
});

test('capture ignores double click and ignores a late response after new buyer reset', async () => {
  const h = harness();
  const pending = h.begin(); await h.begin();
  assert.equal(h.requests.length, 1);
  h.evaluate('newConversation()');
  assert.equal(h.requests[0].options.signal.aborted, true);
  h.el('message').value = 'NEW';
  h.respond(0, preview()); await pending;
  assert.equal(h.el('message').value, 'NEW');
  assert.equal(h.el('qianniuPreviewModal').classList.contains('open'), false);
  assert.equal(h.el('qianniuReadButton').disabled, false);
  h.confirm(); assert.equal(h.el('message').value, 'NEW');
});

test('case selection, raw reset, modal cancel, Escape and conversation id change invalidate capture', async () => {
  for (const action of ["selectCase(0)", 'clearRawContext()', "closeModal('qianniuPreviewModal')", 'closeAllModals()', "setConversationId('another-conversation')"]) {
    const h = harness(), pending = h.begin();
    h.evaluate(action);
    h.respond(0, preview()); await pending;
    assert.equal(h.el('qianniuPreviewModal').classList.contains('open'), false, action);
    assert.equal(h.el('qianniuConfirmButton').disabled, true, action);
  }
});

test('cancelled request cannot replace a newer preview or unlock its controls', async () => {
  const h = harness(), first = h.begin();
  h.evaluate("closeModal('qianniuPreviewModal')");
  const second = h.begin();
  h.respond(0, preview()); await first;
  assert.equal(h.el('qianniuReadButton').disabled, true);
  const data = preview(); data.shop_name = 'NEW SHOP';
  h.respond(1, data); await second;
  h.choose('none'); h.confirm();
  assert.equal(h.el('shopName').value, 'NEW SHOP');
});

test('an earlier analyze result or rejection cannot overwrite an imported buyer', async () => {
  for (const reject of [false, true]) {
    const h = harness(); h.el('message').value = 'OLD';
    const analysis = h.evaluate('runCurrent()');
    await h.ready(); h.choose('none'); h.confirm();
    if (reject) h.requests[0].reject(new Error('OLD ERROR'));
    else h.respond(0, {suggested_reply: 'OLD REPLY'});
    await analysis;
    assert.equal(h.evaluate('lastResponse'), null);
    assert.ok(!h.el('reply').textContent.includes('OLD'));
    assert.equal(h.el('message').value, 'Current buyer question');
  }
});

test('HTTP errors are concise Chinese messages and do not expose raw server details', async () => {
  for (const [status, text] of [[401, /登录/], [403, /权限|校验/], [404, /千牛|窗口/], [422, /会话|读取/], [503, /启用|不可用/]]) {
    const h = harness(), pending = h.begin();
    h.respond(0, {ok: false, error: attack}, status); await pending;
    assert.match(h.el('qianniuStatus').textContent, text);
    assert.ok(!h.el('qianniuStatus').textContent.includes(attack));
    assert.equal(h.el('qianniuConfirmButton').disabled, true);
    assert.equal(h.el('qianniuReadButton').disabled, false);
  }
});

test('invalid roles and unsafe flags fail closed', async () => {
  for (const mutate of [data => {data.context.can_send = true;}, data => {data.context.requires_human_review = false;}, data => {data.context.conversation_history[0].role = 'unknown';}]) {
    const h = harness(), data = preview(); mutate(data); await h.ready(data);
    assert.equal(h.el('qianniuConfirmButton').disabled, true);
    h.choose('none'); h.confirm();
    assert.equal(h.el('message').value, '');
  }
});

test('agent-tail capture keeps all history and leaves current question blank', async () => {
  const h = harness(), data = preview(); data.context.customer_message = ''; data.diagnostics.turn_count = 4;
  await h.ready(data); h.choose('none'); h.confirm();
  assert.equal(h.el('message').value, '');
  assert.deepEqual(h.snapshot('buildPayload().copilot_context.conversation_history'), data.context.conversation_history);
  assert.equal(h.requests.length, 1);
});

test('window mismatch cannot expose an importable preview', async () => {
  const h = harness(), pending = h.begin();
  h.respond(0, {status: 'window_selection_required', windows: [{handle: 99, label: 'Chosen window'}]});
  await pending;
  h.el('qianniuWindowChoice').value = '0';
  const capture = h.evaluate('captureSelectedQianniuWindow()');
  h.respond(1, preview()); await capture;
  h.choose('none'); h.confirm();
  assert.equal(h.el('qianniuConfirmButton').disabled, true);
  assert.equal(h.el('message').value, '');
});

test('duplicate messages stay ordered and cannot be reinterpreted as pasted role markers', async () => {
  const h = harness(), data = preview();
  data.context.conversation_history[0].content = 'customer: repeated';
  data.context.conversation_history[1].content = 'customer: repeated';
  await h.ready(data); h.choose('none'); h.confirm();
  h.el('rawContext').value = 'customer: stale raw textarea';
  assert.deepEqual(h.snapshot('buildPayload().copilot_context.conversation_history'), data.context.conversation_history);
});

test('an explicit pasted replacement retires the imported buyer identity and canonical history', async () => {
  const h = harness(); await h.ready(); h.choose('0'); h.confirm();
  const oldId = h.evaluate('currentConversationId');
  h.el('rawContext').value = 'customer: different buyer';
  h.evaluate('parseRawContext(true)');
  assert.notEqual(h.evaluate('currentConversationId'), oldId);
  assert.equal(h.el('shopName').value, '');
  assert.equal(h.el('orderId').value, '');
  assert.equal(h.el('message').value, 'different buyer');
  assert.deepEqual(h.snapshot('buildPayload().copilot_context.conversation_history'), [{speaker: 'customer', text: 'different buyer'}]);
});

test('explicit analyze uses the same canonical history without product-code promotion', async () => {
  const h = harness(), data = preview(35);
  await h.ready(data); h.choose('0'); h.confirm();
  const run = h.evaluate('runCurrent()');
  assert.equal(h.requests[1].url, '/ask/api/analyze');
  const payload = JSON.parse(h.requests[1].options.body);
  assert.deepEqual(payload.copilot_context.conversation_history, data.context.conversation_history);
  assert.equal(payload.order_id, 'order-A');
  assert.equal(payload.shop_name, 'Preview shop');
  assert.equal(payload.product_candidates, undefined);
  assert.equal(payload.image_attachments, undefined);
  h.respond(1, {suggested_reply: 'Separate manual result', can_send: false, requires_human_review: true});
  await run;
  assert.equal(h.evaluate('lastResponse.suggested_reply'), 'Separate manual result');
  assert.ok(h.el('reply').textContent.includes('Separate manual result') || h.el('reply').innerHTML.includes('Separate manual result'));
});

test('an old batch stops after import instead of selecting the next buyer', async () => {
  const h = harness();
  h.evaluate('CASES.push({message:"old case A"},{message:"old case B"})');
  const batch = h.evaluate('runAll()');
  await h.ready(); h.choose('none'); h.confirm();
  h.respond(0, {suggested_reply: 'OLD'});
  await new Promise(resolve => setImmediate(resolve));
  const count = h.requests.length;
  if (count > 2) h.respond(2, {suggested_reply: 'OLD NEXT CASE'});
  await batch;
  assert.equal(count, 2, 'batch must not make another analyze request after a conversation switch');
  assert.equal(h.el('message').value, 'Current buyer question');
});

test('a truncated canonical response cannot claim the declared captured turn count', async () => {
  const h = harness(), data = preview(31);
  data.context.conversation_history = data.context.conversation_history.slice(-30);
  await h.ready(data); h.choose('none'); h.confirm();
  assert.equal(h.el('message').value, '');
  assert.equal(h.el('qianniuConfirmButton').disabled, true);
});

test('network failure, non-JSON errors and stale rejection stay inert and permit a fresh manual read', async () => {
  const h = harness(), first = h.begin();
  h.requests[0].reject(new Error(attack)); await first;
  assert.ok(!h.el('qianniuStatus').textContent.includes(attack));
  const second = h.begin();
  h.requests[1].resolve({ok: false, status: 503, json: async () => {throw new Error(attack);}});
  await second;
  assert.match(h.el('qianniuStatus').textContent, /启用|不可用/);
  const stale = h.begin(); h.evaluate('newConversation()');
  const current = h.begin(); h.requests[2].reject(new Error(attack)); await stale;
  assert.equal(h.el('qianniuReadButton').disabled, true);
  h.respond(3, preview()); await current;
  assert.equal(h.el('qianniuOrderChoice').value, '');
  assert.equal(h.el('qianniuConfirmButton').disabled, true);
});
