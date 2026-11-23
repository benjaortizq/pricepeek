import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const runtimeSource = await readFile(new URL('./main.js', import.meta.url), 'utf8');

class FakeClassList {
  constructor(initial = []) {
    this.values = new Set(initial);
  }

  contains(name) {
    return this.values.has(name);
  }

  toggle(name, force) {
    if (force) this.values.add(name);
    else this.values.delete(name);
  }
}

class FakeStorage {
  constructor(initial = {}) {
    this.values = new Map(Object.entries(initial));
    this.blocked = false;
  }

  getItem(key) {
    if (this.blocked) throw new Error('Storage blocked');
    return this.values.has(key) ? this.values.get(key) : null;
  }

  setItem(key, value) {
    if (this.blocked) throw new Error('Storage blocked');
    this.values.set(key, String(value));
  }
}

function createPage({ storage = new FakeStorage(), cookie = '', prefersDark = false } = {}) {
  const root = {
    classList: new FakeClassList(['h-full']),
    dataset: {},
  };
  const icon = { textContent: 'dark_mode' };
  const toggle = {
    attributes: {},
    dataset: {
      labelDark: 'Enable dark mode',
      labelLight: 'Enable light mode',
    },
    listeners: {},
    addEventListener(type, handler) {
      this.listeners[type] = handler;
    },
    querySelector(selector) {
      return selector === '[data-theme-icon]' ? icon : null;
    },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
  };
  const document = {
    cookie,
    documentElement: root,
    readyState: 'complete',
    querySelector(selector) {
      return selector === '[data-theme-toggle]' ? toggle : null;
    },
    addEventListener() {},
  };
  const window = {
    document,
    localStorage: storage,
    location: { protocol: 'http:' },
    matchMedia() {
      return { matches: prefersDark };
    },
  };
  const context = vm.createContext({ console, document, window });
  vm.runInContext(runtimeSource, context, { filename: 'main.js' });

  return { document, icon, root, storage, toggle, window };
}

test('the toggle changes the theme and persists it on the next page', () => {
  const firstPage = createPage();

  assert.equal(firstPage.root.dataset.theme, 'light');
  assert.equal(firstPage.toggle.attributes['aria-pressed'], 'false');

  firstPage.toggle.listeners.click();

  assert.equal(firstPage.root.dataset.theme, 'dark');
  assert.ok(firstPage.root.classList.contains('dark'));
  assert.equal(firstPage.icon.textContent, 'light_mode');
  assert.equal(firstPage.toggle.attributes['aria-pressed'], 'true');
  assert.equal(firstPage.storage.getItem('pricepeek-theme'), 'dark');
  assert.match(firstPage.document.cookie, /pricepeek-theme=dark/);

  const nextPage = createPage({
    storage: firstPage.storage,
    cookie: firstPage.document.cookie,
  });

  assert.equal(nextPage.root.dataset.theme, 'dark');
  assert.ok(nextPage.root.classList.contains('dark'));
  assert.equal(nextPage.icon.textContent, 'light_mode');
});

test('the saved theme falls back to the cookie when localStorage is blocked', () => {
  const storage = new FakeStorage();
  storage.blocked = true;
  const page = createPage({
    storage,
    cookie: 'pricepeek-theme=dark; Path=/; SameSite=Lax',
  });

  assert.equal(page.root.dataset.theme, 'dark');
  assert.ok(page.root.classList.contains('dark'));
});
