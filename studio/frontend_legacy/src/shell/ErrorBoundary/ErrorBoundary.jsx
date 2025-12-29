import React from 'react';
import { Icon } from '@iconify/react';
import { Button } from '../../components';
import './ErrorBoundary.css';

/**
 * ErrorBoundary - Catches errors in child components
 *
 * Prevents entire app from crashing when a view has an error.
 * Shows cyberpunk-styled error UI with recovery options.
 */
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    console.error('[ErrorBoundary] Caught error:', error, errorInfo);
    this.setState({
      error,
      errorInfo,
    });

    // Optional: Send to error reporting service
    // reportError(error, errorInfo);
  }

  handleReset = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });

    // Optional: Navigate to safe view
    if (this.props.onReset) {
      this.props.onReset();
    }
  };

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <div className="error-boundary-content">
            {/* Icon */}
            <div className="error-boundary-icon">
              <Icon icon="mdi:alert-octagon" width="64" />
            </div>

            {/* Title */}
            <h1 className="error-boundary-title">Something went wrong</h1>

            {/* Message */}
            <p className="error-boundary-message">
              The view encountered an unexpected error and couldn't render.
            </p>

            {/* Error details (collapsible) */}
            {this.state.error && (
              <details className="error-boundary-details">
                <summary>Error Details</summary>
                <pre className="error-boundary-stack">
                  <code>
                    {this.state.error.toString()}
                    {this.state.errorInfo?.componentStack}
                  </code>
                </pre>
              </details>
            )}

            {/* Actions */}
            <div className="error-boundary-actions">
              <Button variant="primary" icon="mdi:refresh" onClick={this.handleReset}>
                Try Again
              </Button>
              <Button variant="secondary" icon="mdi:reload" onClick={this.handleReload}>
                Reload Page
              </Button>
              <Button
                variant="ghost"
                icon="mdi:home"
                onClick={() => window.location.hash = '#/studio'}
              >
                Go to Studio
              </Button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
