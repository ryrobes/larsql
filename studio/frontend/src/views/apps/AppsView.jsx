/**
 * AppsView - RVBBIT Apps Interface
 *
 * Renders RVBBIT Apps (cascade-powered interfaces) in a full-height iframe.
 * The apps are server-rendered HTML with htmx, so they run independently
 * from React while still being accessible through the Studio sidebar.
 */
import React from 'react';
import './AppsView.css';

const AppsView = () => {
  // In dev mode (port 5550), use absolute URL to Flask backend
  // In prod, Flask serves both the React app and /apps/ endpoint
  const isDev = window.location.port === '5550';
  const appsUrl = isDev ? 'http://localhost:5050/apps/' : '/apps/';

  return (
    <div className="apps-view">
      <iframe
        src={appsUrl}
        className="apps-iframe"
        title="RVBBIT Apps"
      />
    </div>
  );
};

export default AppsView;
