// Search query language, space-separated tokens ANDed together unless
// noted. Quotes group multi-word values; a leading "!" negates any token.
//
//   s:<outcome>   outcome filter; several s: tokens OR together.
//                 s:skipped also matches fixme (a skip flavor).
//   @<tag>        tag filter; several @ tokens AND together.
//   g:<dim>=<val> grouping-dimension filter (file, or any configured
//                 dimension); value is a substring match.
//   case:<id>     case-id substring match.
//   <free text>   substring match over id + caseId + tags + outcome +
//                 group values; several free tokens AND together.
import type { TestData } from '../shared/types';

type Token = { raw: string; negated: boolean; body: string };

export function tokenize(query: string): string[] {
  const re = /"[^"]*"?|'[^']*'?|\S+/g;
  return Array.from(query.matchAll(re), (m) => m[0]);
}

function unquote(s: string): string {
  if (s.length >= 2 && ((s[0] === '"' && s.endsWith('"')) || (s[0] === "'" && s.endsWith("'"))))
    return s.slice(1, -1);
  if (s.length >= 1 && (s[0] === '"' || s[0] === "'")) return s.slice(1);
  return s;
}

function parseToken(raw: string): Token {
  let body = raw;
  let negated = false;
  if (body.startsWith('!')) {
    negated = true;
    body = body.slice(1);
  }
  return { raw, negated, body: unquote(body).toLowerCase() };
}

type Parsed = {
  statuses: Token[];
  tags: Token[];
  groups: { token: Token; dimension: string; value: string }[];
  cases: Token[];
  text: Token[];
};

export class Filter {
  private parsed: Parsed;
  readonly empty: boolean;

  constructor(query: string) {
    const parsed: Parsed = { statuses: [], tags: [], groups: [], cases: [], text: [] };
    for (const raw of tokenize(query)) {
      const token = parseToken(raw);
      if (!token.body) continue;
      if (token.body.startsWith('s:')) {
        parsed.statuses.push({ ...token, body: token.body.slice(2) });
      } else if (token.body.startsWith('@')) {
        parsed.tags.push({ ...token, body: token.body.slice(1) });
      } else if (token.body.startsWith('g:') && token.body.includes('=')) {
        const eq = token.body.indexOf('=');
        parsed.groups.push({
          token,
          dimension: token.body.slice(2, eq),
          value: token.body.slice(eq + 1),
        });
      } else if (token.body.startsWith('case:')) {
        parsed.cases.push({ ...token, body: token.body.slice(5) });
      } else {
        parsed.text.push(token);
      }
    }
    this.parsed = parsed;
    this.empty =
      !parsed.statuses.length &&
      !parsed.tags.length &&
      !parsed.groups.length &&
      !parsed.cases.length &&
      !parsed.text.length;
  }

  matches(test: TestData): boolean {
    const p = this.parsed;

    if (p.statuses.length) {
      const anyStatus = p.statuses.some((t) => {
        const hit =
          t.body === 'skipped'
            ? test.outcome === 'skipped' || test.outcome === 'fixme'
            : test.outcome === t.body;
        return t.negated ? !hit : hit;
      });
      if (!anyStatus) return false;
    }

    const tagsLower = test.tags.map((t) => t.toLowerCase());
    for (const t of p.tags) {
      const hit = tagsLower.some((tag) => tag.includes(t.body));
      if (t.negated ? hit : !hit) return false;
    }

    for (const g of p.groups) {
      const value = (test.groups[g.dimension] || '').toLowerCase();
      const hit = value.includes(g.value);
      if (g.token.negated ? hit : !hit) return false;
    }

    for (const c of p.cases) {
      const hit = (test.caseId || '').toLowerCase().includes(c.body);
      if (c.negated ? hit : !hit) return false;
    }

    if (p.text.length) {
      const blob = searchBlob(test);
      for (const t of p.text) {
        const hit = blob.includes(t.body);
        if (t.negated ? hit : !hit) return false;
      }
    }
    return true;
  }
}

const blobCache = new WeakMap<TestData, string>();

function searchBlob(test: TestData): string {
  let blob = blobCache.get(test);
  if (blob === undefined) {
    blob = [
      test.id,
      test.caseId || '',
      test.tags.join(' '),
      test.outcome,
      Object.values(test.groups).join(' '),
    ]
      .join(' ')
      .toLowerCase();
    blobCache.set(test, blob);
  }
  return blob;
}

function quoteIfNeeded(token: string): string {
  return /\s/.test(token) ? `"${token}"` : token;
}

// Prefix under which a token replaces others of its kind on plain click:
// "s:" replaces any status, "@" any tag, "g:<dim>=" any value of the SAME
// dimension (different dimensions coexist), "case:" any case id.
function tokenPrefix(token: string): string {
  const body = token.startsWith('!') ? token.slice(1) : token;
  if (body.startsWith('s:')) return 's:';
  if (body.startsWith('@')) return '@';
  if (body.startsWith('case:')) return 'case:';
  if (body.startsWith('g:') && body.includes('=')) return body.slice(0, body.indexOf('=') + 1);
  return '';
}

// Shared mutator behind the stats nav and label clicks.
// append=false: replace any same-prefix token with this one.
// append=true: toggle -- add if absent, remove if present.
export function filterWithToken(query: string, token: string, append: boolean): string {
  const tokens = tokenize(query);
  if (append) {
    const idx = tokens.indexOf(token);
    if (idx !== -1) tokens.splice(idx, 1);
    else tokens.push(token);
  } else {
    const prefix = tokenPrefix(token);
    const kept = tokens.filter((t) => {
      const body = t.startsWith('!') ? t.slice(1) : t;
      return prefix === '' ? true : !body.startsWith(prefix);
    });
    kept.push(token);
    tokens.length = 0;
    tokens.push(...kept);
  }
  return tokens.map(quoteIfNeeded).join(' ').trim();
}
