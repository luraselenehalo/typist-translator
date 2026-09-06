import { useMemo } from 'react';
import { call } from '../bridge';
import { useI18n } from '../i18n';
import { Button } from './primitives';

/**
 * Shown once, on the first launch after the app has updated itself.
 *
 * The notes come from the GitHub release body, which is Markdown written for a
 * web page. Rendering it as HTML would mean trusting text fetched from the
 * network with innerHTML, so it is parsed into a small, closed set of shapes -
 * headings, bullets and paragraphs - and rendered as React elements.
 */
function parseNotes(markdown) {
  const blocks = [];
  for (const raw of String(markdown || '').split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    // Skip the decoration: HTML, tables, code fences, images, rules.
    if (/^(<|\||```|---|!\[)/.test(line)) continue;
    if (/^#{1,6}\s/.test(line)) {
      blocks.push({ kind: 'head', text: strip(line.replace(/^#{1,6}\s*/, '')) });
    } else if (/^[-*+]\s/.test(line)) {
      blocks.push({ kind: 'item', text: strip(line.replace(/^[-*+]\s*/, '')) });
    } else if (/^\d+\.\s/.test(line)) {
      blocks.push({ kind: 'item', text: strip(line.replace(/^\d+\.\s*/, '')) });
    } else {
      // Markdown wraps long bullets across source lines. Without this a
      // wrapped bullet becomes a second paragraph starting back at the margin.
      const previous = blocks[blocks.length - 1];
      if (previous && previous.kind !== 'head') {
        previous.text = `${previous.text} ${strip(line)}`.trim();
      } else {
        blocks.push({ kind: 'text', text: strip(line) });
      }
    }
  }
  return blocks.filter((b) => b.text).slice(0, 60);
}

/** Markdown emphasis and links down to their text. */
function strip(text) {
  return text
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/[*_`]+/g, '')
    .trim();
}

export default function WhatsNew({ info, onClose }) {
  const { t } = useI18n();
  const blocks = useMemo(() => parseNotes(info.notes), [info.notes]);

  const dismiss = () => {
    call('dismiss_whats_new').catch(() => {});
    onClose();
  };

  return (
    <div className="modal-backdrop" onMouseDown={dismiss}>
      <div
        className="modal whatsnew"
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="whatsnew__head">
          <span className="whatsnew__spark">🎉</span>
          <div>
            <div className="whatsnew__title">
              {t('whatsnew.title', { version: info.version })}
            </div>
            <div className="whatsnew__sub">{t('whatsnew.sub')}</div>
          </div>
        </div>

        <div className="whatsnew__body">
          {blocks.length === 0 ? (
            <div className="whatsnew__text muted">{t('whatsnew.sub')}</div>
          ) : (
            blocks.map((block, index) => {
              if (block.kind === 'head') {
                return (
                  <div className="whatsnew__section" key={index}>
                    {block.text}
                  </div>
                );
              }
              if (block.kind === 'item') {
                return (
                  <div className="whatsnew__item" key={index}>
                    <span className="whatsnew__dot">•</span>
                    <span>{block.text}</span>
                  </div>
                );
              }
              return (
                <div className="whatsnew__text" key={index}>
                  {block.text}
                </div>
              );
            })
          )}
        </div>

        <div className="whatsnew__actions">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => call('open_link', info.releasesUrl).catch(() => {})}
          >
            {t('whatsnew.full')} ↗
          </Button>
          <span className="grow" />
          <Button variant="primary" onClick={dismiss}>
            {t('whatsnew.close')}
          </Button>
        </div>
      </div>
    </div>
  );
}
