import type { ReportData } from '../shared/types';
import { devFixture } from './devFixture';

declare global {
  interface Window {
    __CTRLRUNNER_REPORT__?: ReportData;
  }
}

// Single choke point for how report data reaches the app. Today it is a
// plain inline JSON assignment injected by render_html(); if reports ever
// grow past a few MB this is the one place to add a zip/base64 channel.
export function loadReportData(): ReportData {
  if (window.__CTRLRUNNER_REPORT__) return window.__CTRLRUNNER_REPORT__;
  if (import.meta.env.DEV) return devFixture;
  return { suiteName: 'ctrlrunner', tests: [], dimensions: [] };
}
