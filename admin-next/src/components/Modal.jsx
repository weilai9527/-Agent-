import { useEffect, useId, useRef } from 'react';
import { X } from 'lucide-react';

export function useFocusTrap(ref, active, onClose) {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!active) return;
    const previous = document.activeElement;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focusable = () => [...ref.current.querySelectorAll('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')]
      .filter(element => element.getClientRects().length > 0);
    const frame = requestAnimationFrame(() => (ref.current.querySelector('[data-autofocus]') ?? focusable()[0] ?? ref.current)?.focus());
    function keydown(event) {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeRef.current();
      }
      if (event.key === 'Tab') {
        const items = focusable();
        const index = items.indexOf(document.activeElement);
        if (!items.length) {
          event.preventDefault();
          ref.current.focus();
        } else if (event.shiftKey && index <= 0) {
          event.preventDefault();
          items.at(-1).focus();
        } else if (!event.shiftKey && (index === items.length - 1 || index === -1)) {
          event.preventDefault();
          items[0].focus();
        }
      }
    }
    document.addEventListener('keydown', keydown);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('keydown', keydown);
      document.body.style.overflow = oldOverflow;
      if (previous?.isConnected) previous.focus();
    };
  }, [active, ref]);
}
export default function Modal({ title, onClose, children }) {
  const ref = useRef(null);
  const id = useId();
  useFocusTrap(ref, true, onClose);
  return (
    <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby={id} ref={ref} tabIndex={-1}>
        <header><h2 id={id}>{title}</h2><button className="icon-button" aria-label="关闭弹窗" onClick={onClose}><X size={20} /></button></header>
        <div className="modal-body">{children}</div>
      </section>
    </div>
  );
}
