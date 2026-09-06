import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { call, on } from './bridge';
import { I18nContext, useTranslator } from './i18n';
import AboutPage from './components/AboutPage';
import EnginesPage from './components/EnginesPage';
import GuidePage from './components/GuidePage';
import HomePage from './components/HomePage';
import LanguagePicker from './components/LanguagePicker';
import SettingsPage from './components/SettingsPage';
import WhatsNew from './components/WhatsNew';
import { Switch, useIndicator } from './components/primitives';

const TABS = [
  ['home', '🏠'],
  ['models', '🤖'],
  ['settings', '⚙️'],
  ['guide', '📖'],
  ['about', 'ℹ️'],
];

/** Resolve "System" against what the OS actually reports. */
function resolveTheme(mode) {
  if (mode === 'Dark') return 'dark';
  if (mode === 'Light') return 'light';
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

export default function App() {
  const [boot, setBoot] = useState(null);
  const [bootError, setBootError] = useState('');
  const [config, setConfig] = useState(null);
  const [history, setHistory] = useState([]);
  const [tab, setTab] = useState('home');
  const [serviceActive, setServiceActive] = useState(true);
  const [picker, setPicker] = useState(null);
  const [whatsNew, setWhatsNew] = useState(null);
  const languageIndex = useRef(new Map());

  /* ------------------------------------------------------------ bootstrap */
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const data = await call('get_bootstrap');
      if (cancelled) return;
      setBoot(data);
      setConfig(data.config);
      setHistory(data.history || []);
      setServiceActive(data.serviceActive);
      // Only ever set on the first launch after the app updated itself.
      if (data.whatsNew) setWhatsNew(data.whatsNew);
      data.popularLanguages?.forEach((lang) =>
        languageIndex.current.set(lang.code, lang),
      );
      window.__TYPIST_POPULAR__ = data.popularLanguages || [];
      document.documentElement.lang = data.config.app_language || 'th';
      // Tell the backend we painted. rAF gives the most accurate moment, but
      // Chromium throttles it to a standstill while the window is occluded or
      // starts hidden, so a timer backstops it. ui_ready is idempotent.
      const signalReady = () => call('ui_ready').catch(() => {});
      requestAnimationFrame(() => requestAnimationFrame(signalReady));
      setTimeout(signalReady, 250);
    })().catch((err) => {
      // Never leave the user staring at a spinner with no explanation.
      console.error('bootstrap failed', err);
      setBootError(String(err?.message || err));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  /* --------------------------------------------------------------- events */
  useEffect(() => {
    const offTranslated = on('translated', (entry) => {
      setHistory((prev) => [entry, ...prev].slice(0, 200));
    });
    const offStatus = on('status', ({ active }) => setServiceActive(active));
    const offConfig = on('config', (next) => setConfig(next));
    return () => {
      offTranslated();
      offStatus();
      offConfig();
    };
  }, []);

  /* ---------------------------------------------------------------- theme */
  const themeMode = config?.appearance_mode || 'System';
  useEffect(() => {
    const apply = () =>
      document.documentElement.setAttribute('data-theme', resolveTheme(themeMode));
    apply();
    if (themeMode !== 'System') return undefined;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, [themeMode]);

  /* ----------------------------------------------------------------- i18n */
  const language = config?.app_language || 'th';
  const i18n = useTranslator(boot?.catalogs, language);

  /* -------------------------------------------------------------- actions */
  const patchConfig = useCallback(async (patch, opts = {}) => {
    // Optimistic: the UI updates immediately, Python persists in the background.
    setConfig((prev) => {
      const next = { ...prev };
      Object.entries(patch).forEach(([key, value]) => {
        next[key] =
          value && typeof value === 'object' && !Array.isArray(value)
            ? { ...(prev[key] || {}), ...value }
            : value;
      });
      return next;
    });
    if (opts.silent) return;
    try {
      const saved = await call('update_config', patch);
      if (saved) setConfig(saved);
    } catch (err) {
      console.error('update_config failed', err);
    }
  }, []);

  const changeLanguage = useCallback(
    (code) => {
      document.documentElement.lang = code;
      patchConfig({ app_language: code });
    },
    [patchConfig],
  );

  const languageOf = useCallback((code) => {
    if (!code) return { code: '', flag: '🌐', nameTh: '', nameEn: '' };
    const cached = languageIndex.current.get(code);
    if (cached) return cached;
    // Unknown code: show it as-is and fetch the real entry in the background.
    const placeholder = { code, flag: '🌐', nameTh: code, nameEn: code };
    languageIndex.current.set(code, placeholder);
    call('get_language', code)
      .then((entry) => {
        if (entry) {
          languageIndex.current.set(code, entry);
          setConfig((prev) => ({ ...prev }));
        }
      })
      .catch(() => {});
    return placeholder;
  }, []);

  const swapPair = useCallback(() => {
    patchConfig({
      swap_lang_a: config.swap_lang_b,
      swap_lang_b: config.swap_lang_a,
    });
  }, [config, patchConfig]);

  const toggleService = useCallback(async (next) => {
    setServiceActive(next);
    await call('set_service_active', next);
  }, []);

  const deleteHistory = useCallback(async (id) => {
    setHistory((prev) => prev.filter((h) => h.id !== id));
    await call('delete_history_entry', id);
  }, []);

  const clearHistory = useCallback(async () => {
    setHistory([]);
    await call('clear_history');
  }, []);

  const addHistoryEntry = useCallback((entry) => {
    if (!entry) return;
    setHistory((prev) => [entry, ...prev.filter((h) => h.id !== entry.id)]
      .slice(0, 200));
  }, []);

  const { navRef, style: indicatorStyle } = useIndicator(tab, [language]);

  if (bootError) {
    return (
      <div className="boot">
        <div className="boot__error">
          <div className="boot__error-title">Could not start</div>
          <pre className="boot__error-body">{bootError}</pre>
        </div>
      </div>
    );
  }

  if (!boot || !config) {
    return (
      <div className="boot">
        <div className="boot__spinner" />
      </div>
    );
  }

  const { t } = i18n;

  return (
    <I18nContext.Provider value={i18n}>
      <div className="app">
        <header className="header">
          <div className="header__brand">
            <img className="header__icon" src="./icon.png" alt="" />
            <div className="header__titles">
              <div className="header__title-row">
                <span className="header__title">{boot.about.appName}</span>
                <span className="badge badge--accent">v{boot.about.version}</span>
              </div>
              <div className="header__tagline">{t('app.tagline')}</div>
            </div>
          </div>

          <div
            className={`status-pill${serviceActive ? '' : ' status-pill--paused'}`}
          >
            <span className="status-pill__dot" />
            {serviceActive ? t('app.status.active') : t('app.status.paused')}
          </div>

          <span className="header__spacer" />

          <div className="header__right">
            <kbd className="keycap keycap--mini">
              {String(config.hotkey || '').toUpperCase().replace(/\+/g, ' + ')}
            </kbd>
            <Switch
              checked={serviceActive}
              onChange={toggleService}
              label={t('app.switch.hotkey')}
            />
          </div>
        </header>

        <nav className="nav" ref={navRef}>
          {TABS.map(([key, icon]) => (
            <button
              key={key}
              type="button"
              className={`nav__item${tab === key ? ' nav__item--active' : ''}`}
              onClick={() => setTab(key)}
            >
              <span>{icon}</span>
              <span>{t(`nav.${key}`)}</span>
            </button>
          ))}
          <span className="nav__indicator" style={indicatorStyle} />
        </nav>

        <main className="content">
          {/* Keyed so switching tabs replays the entrance animation. */}
          <div className="page" key={tab}>
            {tab === 'home' ? (
              <HomePage
                config={config}
                engines={boot.engines}
                history={history}
                languageOf={languageOf}
                onOpenPicker={setPicker}
                onSwapPair={swapPair}
                onDeleteHistory={deleteHistory}
                onClearHistory={clearHistory}
                onTranslated={addHistoryEntry}
              />
            ) : null}
            {tab === 'models' ? (
              <EnginesPage
                config={config}
                engines={boot.engines}
                onPatch={patchConfig}
              />
            ) : null}
            {tab === 'settings' ? (
              <SettingsPage
                config={config}
                defaults={boot.defaults}
                uiLanguages={boot.uiLanguages}
                hotkeyPresets={boot.hotkeyPresets}
                selectionModes={boot.selectionModes}
                themes={boot.themes}
                language={language}
                onPatch={patchConfig}
                onLanguageChange={changeLanguage}
              />
            ) : null}
            {tab === 'guide' ? <GuidePage engines={boot.engines} /> : null}
            {tab === 'about' ? <AboutPage about={boot.about} /> : null}
          </div>
        </main>

        {whatsNew ? (
          <WhatsNew
            info={{
              ...whatsNew,
              releasesUrl: `${boot.about.links.find((l) => l.id === 'releases')?.url
                || 'https://github.com'}`,
            }}
            onClose={() => setWhatsNew(null)}
          />
        ) : null}

        {picker ? (
          <LanguagePicker
            slot={picker}
            current={config[`swap_lang_${picker}`]}
            onClose={() => setPicker(null)}
            onPick={(code) => {
              patchConfig({ [`swap_lang_${picker}`]: code });
              setPicker(null);
            }}
          />
        ) : null}
      </div>
    </I18nContext.Provider>
  );
}
