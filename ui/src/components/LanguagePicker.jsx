import { useEffect, useMemo, useRef, useState } from 'react';
import { call } from '../bridge';
import { useI18n } from '../i18n';
import { Button } from './primitives';

/**
 * Searchable picker over the 100+ language database.
 *
 * The Tk version rebuilt every row on each keystroke; here React reconciles the
 * list, and the query is debounced so the backend search runs at most every
 * 120 ms while typing.
 */
export default function LanguagePicker({ slot, current, onPick, onClose }) {
  const { t, languageName } = useI18n();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const rows = await call('search_languages', query, 40);
        if (!cancelled) {
          setResults(rows || []);
          setHighlight(0);
        }
      } catch {
        if (!cancelled) setResults([]);
      }
    }, query ? 120 : 0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  useEffect(() => {
    const row = listRef.current?.children?.[highlight];
    row?.scrollIntoView({ block: 'nearest' });
  }, [highlight]);

  const title = slot === 'a' ? t('picker.title_a') : t('picker.title_b');

  const onKeyDown = (event) => {
    if (event.key === 'Escape') return onClose();
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setHighlight((h) => Math.min(results.length - 1, h + 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHighlight((h) => Math.max(0, h - 1));
    } else if (event.key === 'Enter' && results[highlight]) {
      onPick(results[highlight].code);
    }
  };

  const popular = useMemo(
    () => (window.__TYPIST_POPULAR__ || []).slice(0, 10),
    [],
  );

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div
        className="modal"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
        role="dialog"
        aria-label={title}
      >
        <div className="modal__head">
          <div className="modal__title">🌐 {title}</div>
          <div className="modal__sub">{t('picker.sub')}</div>
        </div>

        <input
          ref={inputRef}
          className="input"
          placeholder={t('picker.search')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />

        {popular.length ? (
          <>
            <div className="modal__label">{t('picker.popular')}</div>
            <div className="chips">
              {popular.map((lang) => (
                <button
                  key={lang.code}
                  type="button"
                  className={`chip${lang.code === current ? ' chip--active' : ''}`}
                  onClick={() => onPick(lang.code)}
                >
                  {lang.flag} {languageName(lang)}
                </button>
              ))}
            </div>
          </>
        ) : null}

        <div className="modal__list" ref={listRef}>
          {results.length === 0 ? (
            <div className="modal__empty">{t('picker.empty', { query })}</div>
          ) : (
            results.map((lang, index) => {
              const active = lang.code === current;
              return (
                <div
                  key={lang.code}
                  className={[
                    'lang-row',
                    active ? 'lang-row--active' : '',
                    index === highlight ? 'lang-row--highlight' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onMouseEnter={() => setHighlight(index)}
                  onClick={() => onPick(lang.code)}
                >
                  <span className="lang-row__flag">{lang.flag}</span>
                  <span className="grow">
                    <div className="lang-row__name">{languageName(lang)}</div>
                    <div className="lang-row__meta">
                      {lang.nameEn} • [{lang.code}]
                    </div>
                  </span>
                  <Button
                    variant={active ? 'primary' : 'soft'}
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      onPick(lang.code);
                    }}
                  >
                    {active ? t('picker.selected') : t('picker.select')}
                  </Button>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
