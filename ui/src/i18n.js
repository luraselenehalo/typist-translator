/**
 * Interface language.
 *
 * The catalogs come from Python (i18n.py) in the bootstrap payload, so there is
 * exactly one source of translations for both sides of the bridge. Switching
 * language here is a React state change - no window rebuild, unlike the Tk build.
 */
import { createContext, useCallback, useContext, useMemo } from 'react';

const FALLBACK_CHAIN = ['en', 'th'];

export const I18nContext = createContext(null);

export function makeTranslator(catalogs, language) {
  return function t(key, vars) {
    for (const code of [language, ...FALLBACK_CHAIN]) {
      const entry = catalogs?.[code]?.[key];
      if (entry === undefined) continue;
      if (!vars) return entry;
      return entry.replace(/\{(\w+)\}/g, (match, name) =>
        vars[name] === undefined ? match : String(vars[name]),
      );
    }
    return key;
  };
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used inside I18nContext');
  return ctx;
}

export function useTranslator(catalogs, language) {
  const t = useMemo(
    () => makeTranslator(catalogs, language),
    [catalogs, language],
  );

  /** Display name for a language code, in the current interface language. */
  const languageName = useCallback(
    (entry) => {
      if (!entry) return '';
      const key = `lang.${entry.code}`;
      const localized = t(key);
      if (localized !== key) return localized;
      return language === 'th' ? entry.nameTh || entry.nameEn : entry.nameEn;
    },
    [t, language],
  );

  return { t, languageName, language };
}

export function languageLabel(meta) {
  if (!meta) return '';
  return meta.native === meta.english
    ? `${meta.flag}  ${meta.native}`
    : `${meta.flag}  ${meta.native} (${meta.english})`;
}
