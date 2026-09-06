import { useEffect, useMemo, useState } from 'react';
import { call } from '../bridge';
import { useI18n } from '../i18n';
import { Badge, Button, CopyButton, Keycaps } from './primitives';

const SAMPLE_KEYS = ['greet', 'work', 'meeting', 'thanks'];

export default function HomePage({
  config,
  engines,
  history,
  languageOf,
  onOpenPicker,
  onSwapPair,
  onDeleteHistory,
  onClearHistory,
  onTranslated,
}) {
  const { t, languageName } = useI18n();

  const [input, setInput] = useState(() => t('sandbox.default_input'));
  const [output, setOutput] = useState(() => t('sandbox.default_output'));
  const [busy, setBusy] = useState(false);
  const [dots, setDots] = useState('');
  const [outputState, setOutputState] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    if (!busy) {
      setDots('');
      return undefined;
    }
    const id = setInterval(
      () => setDots((d) => (d.length >= 3 ? '' : `${d}.`)),
      260,
    );
    return () => clearInterval(id);
  }, [busy]);

  const engineName = useMemo(() => {
    const found = engines.find((e) => e.id === config.translation_engine);
    return found ? found.name : config.translation_engine;
  }, [engines, config.translation_engine]);

  const langA = languageOf(config.swap_lang_a);
  const langB = languageOf(config.swap_lang_b);

  const runTranslate = async (text) => {
    const value = (text ?? input).trim();
    if (!value || busy) return;
    setBusy(true);
    setOutputState('');
    try {
      const result = await call('translate', value);
      if (result.failed) {
        setOutput(t('error.translate', { msg: result.reason || '' }));
        setOutputState('error');
      } else {
        setOutput(result.translated);
        setOutputState('ok');
        // The backend recorded it; hand the entry straight to the list rather
        // than re-fetching the whole history.
        if (result.entry) onTranslated?.(result.entry);
      }
    } catch (err) {
      setOutput(t('error.translate', { msg: String(err.message || err) }));
      setOutputState('error');
    } finally {
      setBusy(false);
      setTimeout(() => setOutputState(''), 900);
    }
  };

  const loadSample = (key) => {
    const text = t(`sample.${key}`);
    setInput(text);
    runTranslate(text);
  };

  const swapPanes = () => {
    setInput(output);
    setOutput(input);
  };

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return history;
    return history.filter(
      (h) =>
        h.original.toLowerCase().includes(needle) ||
        h.translated.toLowerCase().includes(needle),
    );
  }, [history, query]);

  return (
    <>
      {/* ---------------------------------------------------- stat cards */}
      <div className="stat-grid">
        <div className="card card--hover stat-card">
          <div className="stat-card__head">
            <span className="stat-card__title">{t('home.hotkey.title')}</span>
            <Badge tone="accent">GLOBAL</Badge>
          </div>
          <Keycaps hotkey={config.hotkey} />
          <div className="stat-card__hint">{t('home.hotkey.hint')}</div>
        </div>

        <div className="card card--hover stat-card">
          <div className="stat-card__head">
            <span className="stat-card__title">{t('home.pair.title')}</span>
            <Badge tone="success">AUTO-SWAP</Badge>
          </div>
          <div className="row row--tight" style={{ flexWrap: 'nowrap' }}>
            <Button
              variant="soft"
              className="grow truncate"
              onClick={() => onOpenPicker('a')}
            >
              {langA.flag} {languageName(langA)}
            </Button>
            <Button
              variant="ghost"
              className="btn--icon swap-btn"
              onClick={onSwapPair}
              title={t('home.pair.hint')}
            >
              ↔
            </Button>
            <Button
              variant="soft"
              className="grow truncate"
              onClick={() => onOpenPicker('b')}
            >
              {langB.flag} {languageName(langB)}
            </Button>
          </div>
          <div className="stat-card__hint">{t('home.pair.hint')}</div>
        </div>

        <div className="card card--hover stat-card">
          <div className="stat-card__head">
            <span className="stat-card__title">{t('home.engine.title')}</span>
            <Badge tone="info">ENGINE</Badge>
          </div>
          <div className="engine-name">⚡ {engineName}</div>
          <div className="stat-card__hint">
            {t('home.engine.mode', {
              mode: t(`selection.${config.selection_mode}.badge`),
            })}
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------- sandbox */}
      <div className="card sandbox">
        <div className="row row--tight sandbox__samples">
          <span className="sandbox__samples-label">{t('sandbox.samples')}</span>
          {SAMPLE_KEYS.map((key) => (
            <button
              key={key}
              type="button"
              className="chip chip--sm"
              onClick={() => loadSample(key)}
            >
              {t(`chip.${key}`)}
            </button>
          ))}
        </div>

        <div className="sandbox__panes">
          <div className="sandbox__pane">
            <div className="sandbox__pane-head">
              <span>{t('sandbox.input')}</span>
              <span className="muted">
                {t('sandbox.chars', { n: input.length })}
              </span>
            </div>
            <div className={`sandbox__field${busy ? ' is-busy' : ''}`}>
              <textarea
                className="textarea"
                rows={4}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    runTranslate();
                  }
                }}
              />
              {/* A line sweeping the source text: the same "this is being
                  read right now" idea as the floating chip on the hotkey. */}
              {busy ? <span className="scanline" aria-hidden="true" /> : null}
            </div>
          </div>

          <div className="sandbox__actions">
            <Button
              variant="primary"
              onClick={() => runTranslate()}
              disabled={busy}
            >
              {busy ? t('sandbox.translating', { dots }) : t('sandbox.translate')}
            </Button>
            <Button variant="ghost" size="sm" onClick={swapPanes}>
              ↔
            </Button>
            {busy ? <div className="loader" /> : null}
          </div>

          <div className="sandbox__pane">
            <div className="sandbox__pane-head">
              <span>{t('sandbox.output')}</span>
              <CopyButton
                text={output}
                label={t('action.copy')}
                doneLabel={t('action.copied')}
                onCopy={(text) => call('copy_to_clipboard', text)}
              />
            </div>
            <div className={`sandbox__field${busy ? ' is-busy' : ''}`}>
              <textarea
                className={`textarea textarea--output${
                  outputState ? ` textarea--${outputState}` : ''
                }`}
                rows={4}
                value={output}
                onChange={(e) => setOutput(e.target.value)}
              />
              {/* Covers the previous translation while a new one is running,
                  so a stale result is never mistaken for the fresh one. */}
              {busy ? (
                <div className="skeleton" aria-hidden="true">
                  <span className="skeleton__bar" />
                  <span className="skeleton__bar" />
                  <span className="skeleton__bar" />
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------- history */}
      <div className="row history__head">
        <span className="history__title">{t('history.title')}</span>
        <span className="muted history__count">
          {query
            ? t('history.found', { n: filtered.length })
            : t('history.count', { n: history.length })}
        </span>
        <span className="grow" />
        <input
          className="input history__search"
          placeholder={t('history.search')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Button variant="quiet" size="sm" onClick={onClearHistory}>
          {t('history.clear')}
        </Button>
      </div>

      <div className="card history">
        {filtered.length === 0 ? (
          <div className="history__empty">{t('history.empty')}</div>
        ) : (
          filtered.map((entry) => {
            const src = languageOf(entry.source);
            const tgt = languageOf(entry.target);
            return (
              <div className="history__row fade-in" key={entry.id}>
                <div className="history__meta">
                  <Badge tone="accent">
                    {src.flag} {entry.source.toUpperCase()} → {tgt.flag}{' '}
                    {entry.target.toUpperCase()}
                  </Badge>
                  <span className="muted history__time">{entry.time}</span>
                  <span className="grow" />
                  <CopyButton
                    text={entry.translated}
                    label={t('action.copy')}
                    doneLabel={t('action.copied')}
                    onCopy={(text) => call('copy_to_clipboard', text)}
                  />
                  <Button
                    variant="quiet"
                    size="xs"
                    onClick={() => onDeleteHistory(entry.id)}
                    aria-label="delete"
                  >
                    ✕
                  </Button>
                </div>
                <div className="history__original">{entry.original}</div>
                <div className="history__translated">{entry.translated}</div>
              </div>
            );
          })
        )}
      </div>
    </>
  );
}
