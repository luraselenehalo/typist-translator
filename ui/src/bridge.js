/**
 * Bridge to the Python backend.
 *
 * Every backend method returns {ok, data} or {ok:false, error}. `call` unwraps
 * that so callers get the payload directly and a thrown Error on failure.
 *
 * When the page is opened in a plain browser (`npm run dev`) there is no
 * pywebview object, so a small mock keeps the UI fully explorable without the
 * Python process.
 */

const listeners = new Map();

export function on(eventName, handler) {
  const set = listeners.get(eventName) || new Set();
  set.add(handler);
  listeners.set(eventName, set);
  return () => set.delete(handler);
}

function emit(eventName, payload) {
  const set = listeners.get(eventName);
  if (set) set.forEach((handler) => handler(payload));
}

// Python calls this via evaluate_js.
window.__typistEvent = ({ name, payload }) => emit(name, payload);

const NATIVE_WAIT_MS = 8000;
let nativePromise = null;

/**
 * Is the pywebview bridge actually usable?
 *
 * `window.pywebview.api` is created as an empty object first and its methods
 * are attached a moment later, so testing for the object alone reports ready
 * during a window where every call fails with "No backend method". Requiring
 * at least one method closes that gap.
 */
function bridgeUsable() {
  const api = window.pywebview?.api;
  return Boolean(api && Object.keys(api).length > 0);
}

/**
 * Resolve whether we are running inside pywebview.
 *
 * The API is injected asynchronously and only then does `pywebviewready` fire,
 * so a synchronous check at mount time reports "not native" even in the real
 * app - which silently served the dev mock and rendered raw translation keys.
 * Every call waits on this once, then the answer is cached.
 */
function waitForNative(timeoutMs = NATIVE_WAIT_MS) {
  if (nativePromise) return nativePromise;

  nativePromise = new Promise((resolve) => {
    if (bridgeUsable()) {
      resolve(true);
      return;
    }

    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      clearInterval(poll);
      clearTimeout(bail);
      resolve(value);
    };

    window.addEventListener('pywebviewready', () => {
      if (bridgeUsable()) finish(true);
    });
    const poll = setInterval(() => {
      if (bridgeUsable()) finish(true);
    }, 16);
    // In a plain browser the object never appears; fall through to the mock.
    const bail = setTimeout(() => finish(bridgeUsable()), timeoutMs);
  });

  return nativePromise;
}

/** Wait for one specific method to be attached to the bridge. */
async function resolveMethod(method, timeoutMs = NATIVE_WAIT_MS) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const fn = window.pywebview?.api?.[method];
    if (typeof fn === 'function') return fn;
    if (Date.now() >= deadline) {
      throw new Error(`No backend method "${method}"`);
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

export const isNative = () =>
  typeof window !== 'undefined' && Boolean(window.pywebview?.api);

/** True once any call has actually come back, i.e. the bridge really works. */
let bridgeProven = false;

const HANDSHAKE_TIMEOUT_MS = 1200;
const HANDSHAKE_ATTEMPTS = 8;

function withTimeout(promise, ms) {
  let timer;
  return Promise.race([
    promise.finally(() => clearTimeout(timer)),
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('bridge timeout')), ms);
    }),
  ]);
}

export async function call(method, ...args) {
  const native = await waitForNative();
  if (!native) return mockCall(method, ...args);

  const fn = await resolveMethod(method);

  let result;
  if (bridgeProven) {
    result = await fn(...args);
  } else {
    // Even once a method exists, the very first message can be posted before
    // the transport is routing and would never settle. Retry with a short
    // timeout until one actually comes back, then stop paying for the race.
    let lastError;
    for (let attempt = 0; attempt < HANDSHAKE_ATTEMPTS; attempt += 1) {
      try {
        result = await withTimeout(
          window.pywebview.api[method](...args),
          HANDSHAKE_TIMEOUT_MS,
        );
        bridgeProven = true;
        lastError = undefined;
        break;
      } catch (err) {
        lastError = err;
      }
    }
    if (!bridgeProven) throw lastError || new Error('bridge unavailable');
  }

  if (result && result.ok === false) throw new Error(result.error || method);
  return result ? result.data : undefined;
}

/* ------------------------------------------------------------------ mock */
const mockConfig = {
  hotkey: 'ctrl+alt+t',
  selection_mode: 'all',
  swap_lang_a: 'th',
  swap_lang_b: 'en',
  swap_mode: 'pair',
  translation_engine: 'google_gtx',
  engine_api_keys: { deepl: '', gemini: '', openai: '', groq: '' },
  engine_models: { gemini: 'gemini-1.5-flash', openai: 'gpt-4o-mini' },
  openai_base_url: 'https://api.openai.com/v1',
  sound_effect: true,
  show_toast_notification: true,
  minimize_to_tray_on_close: true,
  start_minimized: false,
  appearance_mode: 'System',
  app_language: 'th',
};

async function mockCall(method, ...args) {
  switch (method) {
    case 'get_bootstrap':
      return {
        config: mockConfig,
        defaults: mockConfig,
        catalogs: window.__MOCK_CATALOGS__ || {},
        uiLanguages: [
          { code: 'th', native: 'ไทย', english: 'Thai', flag: '🇹🇭' },
          { code: 'en', native: 'English', english: 'English', flag: '🇬🇧' },
        ],
        engines: [
          {
            id: 'google_gtx',
            name: 'Google Translate',
            needsKey: false,
            badgeFallback: 'free',
            descFallback: 'mock',
          },
        ],
        selectionModes: ['all', 'smart', 'line', 'selection'],
        hotkeyPresets: ['ctrl+alt+t', 'f8'],
        themes: ['System', 'Dark', 'Light'],
        popularLanguages: [
          { code: 'th', flag: '🇹🇭', nameTh: 'ไทย', nameEn: 'Thai' },
          { code: 'en', flag: '🇬🇧', nameTh: 'อังกฤษ', nameEn: 'English' },
        ],
        history: [],
        serviceActive: true,
      };
    case 'translate':
      await new Promise((r) => setTimeout(r, 400));
      return {
        translated: `[mock] ${args[0]}`,
        source: 'th',
        target: 'en',
        failed: false,
      };
    case 'update_config':
      Object.assign(mockConfig, args[0]);
      return mockConfig;
    case 'search_languages':
      return [{ code: 'th', flag: '🇹🇭', nameTh: 'ไทย', nameEn: 'Thai' }];
    default:
      return {};
  }
}
