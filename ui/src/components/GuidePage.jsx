import { useI18n } from '../i18n';
import { Badge, Section } from './primitives';

const PAIRS = [
  { flagA: '🇹🇭', flagB: '🇯🇵', a: 'th', b: 'ja' },
  { flagA: '🇹🇭', flagB: '🇨🇳', a: 'th', b: 'zh-CN' },
  { flagA: '🇬🇧', flagB: '🇪🇸', a: 'en', b: 'es' },
];

export default function GuidePage({ engines }) {
  const { t } = useI18n();

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

  return (
    <>
      <div className="card guide-hero">
        <div className="guide-hero__title">{t('guide.hero.title')}</div>
        <div className="guide-hero__sub">{t('guide.hero.sub')}</div>
      </div>

      {[1, 2, 3].map((n) => (
        <div className="card card--sunken card--hover guide-step" key={n}>
          <span className="guide-step__num">{n}</span>
          <div>
            <div className="guide-step__title">{t(`guide.step${n}.title`)}</div>
            <div className="guide-step__desc">{t(`guide.step${n}.desc`)}</div>
          </div>
        </div>
      ))}

      <Section title={t('guide.pairs.title')} />
      <div className="guide-pairs">
        {PAIRS.map((pair) => {
          const nameA = t(`lang.${pair.a}`);
          const nameB = t(`lang.${pair.b}`);
          return (
            <div className="card card--sunken card--hover guide-pair" key={pair.b}>
              <div className="guide-pair__flags">
                {pair.flagA} {pair.flagB}
              </div>
              <div className="guide-pair__title">
                {nameA} <span className="guide-pair__arrow">↔</span> {nameB}
              </div>
              <div className="guide-pair__desc">
                {t('guide.pair.desc', { a: nameA, b: nameB })}
              </div>
            </div>
          );
        })}
      </div>
      <div className="muted guide-note">{t('guide.pairs.note')}</div>

      <Section title={t('guide.engines.title')} />
      {engines.map((engine) => (
        <div className="card card--sunken card--hover guide-engine" key={engine.id}>
          <div className="row row--tight">
            <span className="guide-engine__name">{engine.name}</span>
            <span className="grow" />
            <Badge tone={engine.needsKey ? 'warning' : 'success'}>
              {badgeOf(engine)}
            </Badge>
          </div>
          <div className="guide-engine__desc">{descOf(engine)}</div>
        </div>
      ))}
    </>
  );
}
