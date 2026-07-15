import React from 'react';
import ReactDOM from 'react-dom/client';
import '../shared/tokens.css';
import './app.css';
import { applyTheme } from '../shared/theme';
import { UiApp } from './uiApp';

applyTheme();

const root = document.getElementById('root');
if (!root) throw new Error('missing #root element in UI page');

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <UiApp />
  </React.StrictMode>,
);
