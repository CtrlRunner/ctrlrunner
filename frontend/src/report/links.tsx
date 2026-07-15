// Tiny hash router: all view state (filter query, open test, attempt,
// grouping dimension) lives in location.hash as "#?key=value&..." so
// every view is deep-linkable and back/forward just works.
import React from 'react';

function parseHash(): URLSearchParams {
  const hash = window.location.hash;
  const idx = hash.indexOf('?');
  return new URLSearchParams(idx === -1 ? '' : hash.slice(idx + 1));
}

const SearchParamsContext = React.createContext<URLSearchParams>(new URLSearchParams());

export function SearchParamsProvider({ children }: { children: React.ReactNode }) {
  const [params, setParams] = React.useState(parseHash);
  React.useEffect(() => {
    const onPopState = () => setParams(parseHash());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);
  return <SearchParamsContext.Provider value={params}>{children}</SearchParamsContext.Provider>;
}

export function useSearchParams(): URLSearchParams {
  return React.useContext(SearchParamsContext);
}

export function hashFor(params: URLSearchParams): string {
  const s = params.toString();
  return `#?${s}`;
}

export function navigate(href: string | URLSearchParams): void {
  const target = typeof href === 'string' ? href : hashFor(href);
  window.history.pushState({}, '', target);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export function withParam(
  params: URLSearchParams,
  key: string,
  value: string | null,
): URLSearchParams {
  const next = new URLSearchParams(params);
  if (value === null) next.delete(key);
  else next.set(key, value);
  return next;
}

export function Link({
  href,
  ctrlHref,
  className,
  title,
  children,
}: {
  href: string;
  ctrlHref?: string;
  className?: string;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <a
      className={className}
      title={title}
      href={href}
      onClick={(e) => {
        // Let real browser affordances (middle click, cmd-click on plain
        // links) work only when no alternate URL is provided.
        if ((e.metaKey || e.ctrlKey) && ctrlHref) {
          e.preventDefault();
          navigate(ctrlHref);
          return;
        }
        e.preventDefault();
        navigate(e.metaKey || e.ctrlKey ? (ctrlHref ?? href) : href);
      }}
    >
      {children}
    </a>
  );
}
