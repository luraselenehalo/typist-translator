import { useEffect, useLayoutEffect, useRef, useState } from 'react';

export function Badge({ tone = 'accent', children }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

export function Button({
  variant = 'primary',
  size,
  className = '',
  children,
  ...rest
}) {
  const classes = [
    'btn',
    `btn--${variant}`,
    size ? `btn--${size}` : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <button type="button" className={classes} {...rest}>
      {children}
    </button>
  );
}

export function Section({ title, sub }) {
  return (
    <div className="section">
      <div className="section__title">{title}</div>
      {sub ? <div className="section__sub">{sub}</div> : null}
    </div>
  );
}

export function Switch({ checked, onChange, label }) {
  return (
    <label className="switch">
      <span
        className={`switch__track${checked ? ' switch__track--on' : ''}`}
        role="switch"
        aria-checked={checked}
        tabIndex={0}
        onClick={() => onChange(!checked)}
        onKeyDown={(e) => {
          if (e.key === ' ' || e.key === 'Enter') {
            e.preventDefault();
            onChange(!checked);
          }
        }}
      >
        <span className="switch__thumb" />
      </span>
      {label ? <span>{label}</span> : null}
    </label>
  );
}

export function Keycaps({ hotkey, mini = false }) {
  const parts = String(hotkey || '')
    .split('+')
    .map((p) => p.trim().toUpperCase())
    .filter(Boolean);
  return (
    <div className="keycaps">
      {parts.map((part, i) => (
        <span key={`${part}-${i}`} style={{ display: 'contents' }}>
          {i > 0 ? <span className="keycaps__plus">+</span> : null}
          <kbd className={`keycap${mini ? ' keycap--mini' : ''}`}>{part}</kbd>
        </span>
      ))}
    </div>
  );
}

/**
 * A button that briefly confirms, then reverts.
 * Used for every copy action so the feedback is consistent.
 */
export function CopyButton({ text, label, doneLabel, onCopy, size = 'xs' }) {
  const [done, setDone] = useState(false);
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <Button
      variant={done ? 'success' : 'ghost'}
      size={size}
      onClick={async () => {
        await onCopy(text);
        setDone(true);
        clearTimeout(timer.current);
        timer.current = setTimeout(() => setDone(false), 1200);
      }}
    >
      {done ? doneLabel : label}
    </Button>
  );
}

/**
 * Sliding underline for the tab bar. Measured from the DOM so it stays correct
 * at any window width and in any interface language.
 */
export function useIndicator(activeKey, deps = []) {
  const navRef = useRef(null);
  const [style, setStyle] = useState({ width: 0, transform: 'translateX(0)' });

  useLayoutEffect(() => {
    const nav = navRef.current;
    if (!nav) return undefined;

    const measure = () => {
      const active = nav.querySelector('.nav__item--active');
      if (!active) return;
      const navBox = nav.getBoundingClientRect();
      const box = active.getBoundingClientRect();
      const inset = Math.max(8, box.width * 0.22);
      setStyle({
        width: Math.max(24, box.width - inset * 2),
        transform: `translateX(${box.left - navBox.left + inset}px)`,
      });
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(nav);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeKey, ...deps]);

  return { navRef, style };
}
