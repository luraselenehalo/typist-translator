import { call } from '../bridge';
import { useI18n } from '../i18n';
import { Badge, Button, CopyButton, Section } from './primitives';

const STORY_KEYS = ['what', 'how', 'privacy'];
const STORY_ICONS = { what: '⚡', how: '🧩', privacy: '🔒' };

/**
 * Everything on this page comes from about.py through the bootstrap payload,
 * so the author and the links are edited in one Python file and picked up on
 * the next launch - no `npm run build` to change a URL.
 */
export default function AboutPage({ about }) {
  const { t } = useI18n();

  // Links leave the app, so they go to the system browser. An <a href> would
  // navigate this window itself, and it has no address bar to come back with.
  const openLink = (url) => call('open_link', url).catch(() => {});

  return (
    <>
      <div className="card about-hero">
        <img className="about-hero__icon" src="./icon.png" alt="" />
        <div className="about-hero__text">
          <div className="about-hero__title-row">
            <span className="about-hero__title">
              {t('about.hero.title', { app: about.appName })}
            </span>
            <Badge tone="accent">{t('about.version', { version: about.version })}</Badge>
          </div>
          <div className="about-hero__sub">{t('about.hero.sub')}</div>
          <div className="about-hero__by">
            {t('about.hero.by', { author: about.author })}
          </div>
          {about.alias ? (
            <div className="about-hero__alias">
              {t('about.alias', { author: about.author, alias: about.alias })}
            </div>
          ) : null}
        </div>
      </div>

      {STORY_KEYS.map((key) => (
        <div className="card card--sunken card--hover about-story" key={key}>
          <span className="about-story__icon">{STORY_ICONS[key]}</span>
          <div>
            <div className="about-story__title">{t(`about.${key}.title`)}</div>
            <div className="about-story__body">{t(`about.${key}.body`)}</div>
          </div>
        </div>
      ))}

      <Section title={t('about.tech.title')} />
      <div className="row row--tight about-tech">
        {about.builtWith.map((item) => (
          <span className="chip chip--sm about-tech__chip" key={item.name}>
            {item.name}
            <span className="about-tech__version">{item.version}</span>
          </span>
        ))}
      </div>

      <Section title={t('about.links.title')} />
      {about.links.length === 0 ? (
        <div className="card card--sunken about-links__empty">
          {t('about.links.empty', { file: about.linksFile })}
        </div>
      ) : (
        <div className="about-links">
          {about.links.map((link) => (
            <div className="card card--sunken card--hover about-link" key={link.id}>
              <span className="about-link__icon">{link.icon}</span>
              <div className="about-link__text">
                <div className="about-link__title">{t(`about.link.${link.id}`)}</div>
                <div className="about-link__sub">{t(`about.link.${link.id}.sub`)}</div>
                <div className="about-link__url mono">{link.url}</div>
              </div>
              <div className="about-link__actions">
                <Button variant="soft" size="sm" onClick={() => openLink(link.url)}>
                  {t('about.open')} ↗
                </Button>
                <CopyButton
                  text={link.url}
                  label={t('action.copy')}
                  doneLabel={t('action.copied')}
                  onCopy={(text) => call('copy_to_clipboard', text)}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      <Section title={t('about.license.title')} />
      <div className="card card--sunken about-license">
        <Badge tone="success">{about.license}</Badge>
        <span>{t('about.license.body', { license: about.license })}</span>
      </div>

      <div className="about-footer muted">{about.copyright}</div>
    </>
  );
}
