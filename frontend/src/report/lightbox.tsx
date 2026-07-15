import React from 'react';

export function Lightbox({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div className="lightbox-backdrop" onClick={onClose} role="presentation">
      <button
        type="button"
        className="lightbox-close"
        onClick={onClose}
        aria-label="Close image preview"
      >
        ×
      </button>
      <img className="lightbox-img" src={src} alt={alt} onClick={(e) => e.stopPropagation()} />
    </div>
  );
}
