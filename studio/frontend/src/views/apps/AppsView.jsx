/**
 * AppsView - LARS Apps Interface
 *
 * Renders LARS Apps (cascade-powered interfaces) in a full-height iframe.
 * The apps are server-rendered HTML with htmx, so they run independently
 * from React while still being accessible through the Studio sidebar.
 */
import React from 'react';
import './AppsView.css';
import { API_BASE_URL } from '../../config/api';

const AppsView = () => {
  // In dev mode (port 5550), use absolute URL to Flask backend
  // In prod, Flask serves both the React app and /apps/ endpoint
  const isDev = window.location.port === '5550';
  const appsUrl = isDev ? `${API_BASE_URL}/apps/` : '/apps/';

  return (
    <div className="apps-view">
      <iframe
        src={appsUrl}
        className="apps-iframe"
        title="LARS Apps"
      />
    </div>
  );
};

export default AppsView;
