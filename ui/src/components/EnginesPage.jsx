import { useState } from 'react';
import { call } from '../bridge';
import { useI18n } from '../i18n';
import { Badge, Button, Section } from './primitives';

const GEMINI_MODELS = ['gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-1.5-pro'];

export default function EnginesPage({ config, engines, onPatch }) {
  const { t } = useI18n();
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const activeId = config.translation_engine;
  const active = engines.find((e) => e.id === activeId) || engines[0];

  const badgeOf = (engine) => {
    const key = `engine.${engine.id}.badge`;
    const value = t(key);
    return value === key ? engine.badgeFallback : value;
  };
  const descOf = (engine) => {
    const key = `engine.${engine.id}.desc`;
    const value = t(key);
    return value === key ? engine.descFallback : value;
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await call('test_engine', activeId);
      setTestResult(result);
    } catch (err) {
      setTestResult({ ok: false, message: String(err.message || err) });
    } finally {
      setTesting(false);
    }
  };

  const setKey = (service, value) =>
    onPatch({ engine_api_keys: { [service]: value } });
  const setModel = (service, value) =>
    onPatch({ engine_models: { [service]: value } });

  return (
    <>
      <div className="card card--sunken pad">
        <div className="page__title">{t('models.head.title')}</div>
        <div className="section__sub">{t('models.head.desc')}</div>
      </div>

      <Section title={t('models.section1.title')} sub={t('models.section1.sub')} />

      <div className="engine-list">
        {engines.map((engine) => {
          const selected = engine.id === activeId;
          return (
            <button
              key={engine.id}
              type="button"
              className={`engine-card${selected ? ' engine-card--active' : ''}`}
              onClick={() => onPatch({ translation_engine: engine.id })}
            >
              <div className="engine-card__head">
                <span className="engine-card__radio">{selected ? '●' : '○'}</span>
                <span className="engine-card__name">{engine.name}</span>
                <span className="grow" />
                <Badge tone={engine.needsKey ? 'warning' : 'success'}>
                  {badgeOf(engine)}
                </Badge>
              </div>
              <div className="engine-card__desc">{descOf(engine)}</div>
            </button>
          );
        })}
      </div>

      <Section title={t('models.section2.title')} sub={t('models.section2.sub')} />

      <div className="card card--sunken pad credentials">
        {activeId === 'deepl' ? (
          <label className="field">
            <span className="field__label">{t('models.deepl.key')}</span>
            <input
              className="input"
              type="password"
              placeholder={t('models.deepl.placeholder')}
              value={config.engine_api_keys?.deepl || ''}
              onChange={(e) => setKey('deepl', e.target.value)}
            />
          </label>
        ) : null}

        {activeId === 'gemini' ? (
          <>
            <label className="field">
              <span className="field__label">{t('models.gemini.key')}</span>
              <input
                className="input"
                type="password"
                placeholder={t('models.gemini.placeholder')}
                value={config.engine_api_keys?.gemini || ''}
                onChange={(e) => setKey('gemini', e.target.value)}
              />
            </label>
            <label className="field">
              <span className="field__label">{t('models.gemini.model')}</span>
              <select
                className="select"
                value={config.engine_models?.gemini || GEMINI_MODELS[0]}
                onChange={(e) => setModel('gemini', e.target.value)}
              >
                {GEMINI_MODELS.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : null}

        {activeId === 'openai' ? (
          <>
            <label className="field">
              <span className="field__label">{t('models.openai.key')}</span>
              <input
                className="input"
                type="password"
                placeholder="sk-..."
                value={config.engine_api_keys?.openai || ''}
                onChange={(e) => setKey('openai', e.target.value)}
              />
            </label>
            <label className="field">
              <span className="field__label">{t('models.openai.model')}</span>
              <input
                className="input"
                value={config.engine_models?.openai || ''}
                onChange={(e) => setModel('openai', e.target.value)}
              />
            </label>
            <label className="field">
              <span className="field__label">{t('models.openai.base_url')}</span>
              <input
                className="input"
                value={config.openai_base_url || ''}
                onChange={(e) => onPatch({ openai_base_url: e.target.value })}
              />
            </label>
          </>
        ) : null}

        {active && !active.needsKey ? (
          <div className="ready-note">{t('models.free_ready')}</div>
        ) : null}
      </div>

      <div className="row">
        <Button variant="primary" onClick={runTest} disabled={testing}>
          {testing ? t('models.testing') : t('models.test')}
        </Button>
        {testResult ? (
          <span
            className={`test-result test-result--${testResult.ok ? 'ok' : 'fail'}`}
          >
            {testResult.ok
              ? t('models.test_ok', { ms: testResult.latency })
              : t('models.test_fail', { msg: testResult.message })}
          </span>
        ) : null}
      </div>
    </>
  );
}
