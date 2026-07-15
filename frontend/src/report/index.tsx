import React from 'react';
import ReactDOM from 'react-dom/client';
import '../shared/tokens.css';
import './app.css';
import { applyTheme } from '../shared/theme';
import { SearchParamsProvider } from './links';
import { loadReportData } from './loadReportData';
import { ReportApp } from './reportApp';

applyTheme();
const report = loadReportData();
document.title = `${report.suiteName} — ctrlrunner report`;

const root = document.getElementById('root');
if (!root) throw new Error('missing #root element in report page');

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <SearchParamsProvider>
      <ReportApp report={report} />
    </SearchParamsProvider>
  </React.StrictMode>,
);
