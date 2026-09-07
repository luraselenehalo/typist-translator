import { useEffect, useState } from 'react';
import { call } from '../bridge';
import { languageLabel, useI18n } from '../i18n';
import { Button, Section } from './primitives';

const PREF_KEYS = [
  ['check_for_updates', 'settings.prefs.autoupdate'],
  ['show_progress_overlay', 'settings.prefs.overlay'],
  ['show_toast_notification', 'settings.prefs.toast'],
  ['sound_effect', 'settings.prefs.sound'],
  ['restore_clipboard', 'settings.prefs.restore_clipboard'],
  ['minimize_to_tray_on_close', 'settings.prefs.tray'],
  ['start_minimized', 'settings.prefs.start_min'],
];

export default function SettingsPage({
  config,
  defaults,
  uiLanguages,
  hotkeyPresets,
  selectionModes,
  themes,
  language,
  onPatch,
  onLanguageChange,
}) {
  const { t } = useI18n();
  const [hotkeyDraft, setHotkeyDraft] = useState(config.hotkey || '');
  const [hotkeyError, setHotkeyError] = useState('');
  const [undoDraft, setUndoDraft] = useState(config.undo_hotkey || '');
  const [undoError, setUndoError] = useState('');
  const [saved, setSaved] = useState(false);
  const [updateNote, setUpdateNote] = useState('');
  const [checking, setChecking] = useState(false);

  useEffect(() => setHotkeyDraft(config.hotkey || ''), [config.hotkey]);
  useEffect(() => setUndoDraft(config.undo_hotkey || ''), [config.undo_hotkey]);

  const applyHotkey = async (value) => {
    const result = await call('set_hotkey', value);
    if (result.registered) {
      setHotkeyError('');
      onPatch({ hotkey: value }, { silent: true });
      flashSaved();
    } else {
      setHotkeyError(t('settings.hotkey.error', { msg: result.message }));
    }
  };

  // Emptying the field is how undo is switched off, so '' is a valid value
  // here and must not be rejected the way an empty translate hotkey is.
  const applyUndoHotkey = async (value) => {
    const result = await call('set_undo_hotkey', value);
    if (result.registered) {
      setUndoError('');
      onPatch({ undo_hotkey: value, enable_undo: Boolean(value) }, { silent: true });
      flashSaved();
    } else {
      setUndoError(t('settings.hotkey.undo_error', { msg: result.message }));
      setUndoDraft(config.undo_hotkey || '');
    }
  };

  const flashSaved = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const resetDefaults = async () => {
    const patch = {
      selection_mode: defaults.selection_mode,
      check_for_updates: defaults.check_for_updates,
      show_progress_overlay: defaults.show_progress_overlay,
      show_toast_notification: defaults.show_toast_notification,
      sound_effect: defaults.sound_effect,
      restore_clipboard: defaults.restore_clipboard,
      output_mode: defaults.output_mode,
      minimize_to_tray_on_close: defaults.minimize_to_tray_on_close,
      start_minimized: defaults.start_minimized,
      appearance_mode: defaults.appearance_mode,
    };
    onPatch(patch);
    setHotkeyDraft(defaults.hotkey);
    await applyHotkey(defaults.hotkey);
    setUndoDraft(defaults.undo_hotkey);
    await applyUndoHotkey(defaults.undo_hotkey);
  };

  const presetValue = hotkeyPresets.includes(hotkeyDraft) ? hotkeyDraft : '__custom__';

  const checkForUpdates = async () => {
    setChecking(true);
    setUpdateNote(t('update.check.checking'));
    try {
      const result = await call('check_for_updates');
      if (result?.status === 'available') {
        setUpdateNote(t('update.check.found', { version: result.version }));
      } else if (result?.status === 'current') {
        setUpdateNote(t('update.check.current', { version: result.version }));
      } else {
        setUpdateNote(result?.message || '');
      }
    } catch (err) {
      setUpdateNote(String(err?.message || err));
    } finally {
      setChecking(false);
    }
  };

  return (
    <>
      {/* 1. Interface language first: it decides how the rest of this page reads. */}
      <Section
        title={t('settings.language.title')}
        sub={t('settings.language.sub')}
      />
      <select
        className="select settings__control"
        value={language}
        onChange={(e) => onLanguageChange(e.target.value)}
      >
        {uiLanguages.map((meta) => (
          <option key={meta.code} value={meta.code}>
            {languageLabel(meta)}
          </option>
        ))}
      </select>

      <Section title={t('settings.hotkey.title')} sub={t('settings.hotkey.sub')} />
      <div className="row">
        <select
          className="select settings__control"
          value={presetValue}
          onChange={(e) => {
            if (e.target.value === '__custom__') return;
            setHotkeyDraft(e.target.value);
            applyHotkey(e.target.value);
          }}
        >
          {hotkeyPresets.map((preset) => (
            <option key={preset} value={preset}>
              {preset}
            </option>
          ))}
          <option value="__custom__">{t('settings.hotkey.custom')}</option>
        </select>
        <input
          className="input mono settings__control"
          placeholder={t('settings.hotkey.placeholder')}
          value={hotkeyDraft}
          onChange={(e) => setHotkeyDraft(e.target.value)}
          onBlur={() => {
            if (hotkeyDraft && hotkeyDraft !== config.hotkey) {
              applyHotkey(hotkeyDraft.trim().toLowerCase());
            }
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.currentTarget.blur();
          }}
        />
      </div>
      {hotkeyError ? <div className="error-note">{hotkeyError}</div> : null}

      <div className="row settings__undo">
        <span className="settings__inline-label">{t('settings.hotkey.undo')}</span>
        <input
          className="input mono settings__control"
          placeholder={t('settings.hotkey.undo_placeholder')}
          value={undoDraft}
          onChange={(e) => setUndoDraft(e.target.value)}
          onBlur={() => {
            const next = undoDraft.trim().toLowerCase();
            if (next !== (config.undo_hotkey || '')) applyUndoHotkey(next);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.currentTarget.blur();
          }}
        />
      </div>
      <div className="settings__hint">{t('settings.hotkey.undo_sub')}</div>
      {undoError ? <div className="error-note">{undoError}</div> : null}

      <Section
        title={t('settings.selection.title')}
        sub={t('settings.selection.sub')}
      />
      <select
        className="select settings__control settings__control--wide"
        value={config.selection_mode}
        onChange={(e) => onPatch({ selection_mode: e.target.value })}
      >
        {selectionModes.map((mode) => (
          <option key={mode} value={mode}>
            {`${t(`selection.${mode}.badge`)} — ${t(`selection.${mode}.desc`)}`}
          </option>
        ))}
      </select>

      <Section title={t('settings.prefs.title')} />
      <div className="prefs">
        {PREF_KEYS.map(([key, labelKey]) => (
          <label className="checkrow" key={key}>
            <input
              type="checkbox"
              checked={Boolean(config[key])}
              onChange={(e) => onPatch({ [key]: e.target.checked })}
            />
            <span>{t(labelKey)}</span>
          </label>
        ))}
      </div>

      <Section
        title={t('settings.output.title')}
        sub={t('settings.output.sub')}
      />
      <select
        className="select settings__control settings__control--wide"
        value={config.output_mode || 'paste'}
        onChange={(e) => onPatch({ output_mode: e.target.value })}
      >
        <option value="paste">{t('settings.output.paste')}</option>
        <option value="type">{t('settings.output.type')}</option>
      </select>

      <Section title={t('settings.theme.title')} />
      <select
        className="select settings__control"
        value={config.appearance_mode}
        onChange={(e) => onPatch({ appearance_mode: e.target.value })}
      >
        {themes.map((theme) => (
          <option key={theme} value={theme}>
            {t(`theme.${theme}`)}
          </option>
        ))}
      </select>

      <div className="row settings__actions">
        <Button variant="soft" onClick={checkForUpdates} disabled={checking}>
          {checking ? t('update.check.checking') : t('update.check.now')}
        </Button>
        {updateNote ? (
          <span className="muted settings__update-note">{updateNote}</span>
        ) : null}
      </div>

      <div className="row settings__actions">
        <Button variant="quiet" onClick={resetDefaults}>
          {t('settings.reset')}
        </Button>
        {saved ? <span className="saved-note">{t('settings.saved')}</span> : null}
        <span className="grow" />
        <span className="muted settings__autosave">{t('models.section2.sub')}</span>
      </div>
    </>
  );
}
