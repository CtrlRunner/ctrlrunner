import type { ReportData } from '../shared/types';
import { devFixture } from './devFixture';

declare global {
  interface Window {
    __PYRUNNER_REPORT__?: ReportData;
  }
}

// Single choke point for how report data reaches the app. Today it is a
// plain inline JSON assignment injected by render_html(); if reports ever
// grow past a few MB this is the one place to add a zip/base64 channel.
export function loadReportData(): ReportData {
  if (window.__PYRUNNER_REPORT__) return window.__PYRUNNER_REPORT__;
  if (import.meta.env.DEV) return devFixture;
  return { suiteName: 'pyrunner', tests: [], dimensions: [] };
}
