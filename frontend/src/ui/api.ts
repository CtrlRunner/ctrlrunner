// Typed client for ui_server.py's HTTP + SSE contract.
import type { Step } from '../shared/types';

declare global {
  interface Window {
    CTRLRUNNER_SESSION_TOKEN?: string;
  }
}

export function sessionToken(): string {
  // render_ui_html() replaces every occurrence of the full placeholder
  // string, so the bundle must never contain it verbatim (a minifier
  // constant-folds even split concatenations). Recognizing an unreplaced
  // placeholder by its prefix avoids embedding the full literal.
  const embedded = window.CTRLRUNNER_SESSION_TOKEN || '';
  if (embedded && !embedded.startsWith('__CTRLRUNNER')) return embedded;
  // Dev-only escape: the Vite dev server can't receive the embedded
  // token, so allow passing it as ?token=.
  if (import.meta.env.DEV) return new URLSearchParams(location.search).get('token') || '';
  return '';
}

export function apiPost(path: string, body?: unknown): Promise<Response> {
  return fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Ctrlrunner-Token': sessionToken(),
    },
    body: JSON.stringify(body || {}),
  });
}

export type TestInfo = {
  id: string;
  caseId?: string | null;
  groups?: Record<string, string>;
};

// UI Mode results are leaner than report results: artifacts are plain
// path strings served under /ctrlrunner-artifacts/.
export type LiveResult = {
  id: string;
  outcome: string;
  duration: number;
  error?: string | null;
  steps?: Step[];
  artifacts?: string[];
  groups?: Record<string, string>;
  quarantined?: boolean;
  quarantineReason?: string | null;
  nearTimeout?: boolean;
};

export type TestsPayload = {
  tests: TestInfo[];
  dimensions?: string[];
  numWorkers: number;
  numWorkersSetting?: string | number;
  lastResults?: Record<string, LiveResult>;
  traceViewerUrl?: string | null;
  lastTracedTestId?: string | null;
};

export type RunEvent =
  | { type: 'run_start'; total: number; traceViewerUrl?: string | null }
  | { type: 'test_start'; id: string }
  | ({ type: 'test_end' } & LiveResult)
  | { type: 'run_end'; passed: number; failed: number; total: number; duration: number };

export async function fetchTests(): Promise<TestsPayload> {
  const res = await fetch('/api/tests');
  return res.json();
}

export async function fetchStatus(): Promise<{ status: string }> {
  const res = await fetch('/api/status');
  return res.json();
}

export function subscribeEvents(onEvent: (ev: RunEvent) => void): () => void {
  const es = new EventSource('/api/events');
  es.onmessage = (e) => onEvent(JSON.parse(e.data));
  return () => es.close();
}
