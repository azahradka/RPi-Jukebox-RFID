import React from 'react';

import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';

/**
 * Top-level error boundary for the Phoniebox Web UI.
 *
 * Phase 1, fix #7: ``request.js`` now throws on RPC errors instead of
 * silently returning ``{ error }``. Any uncaught error bubbles up to
 * this boundary, which renders a recovery panel with a retry button.
 *
 * React class components are still the only way to implement
 * ``componentDidCatch`` / ``getDerivedStateFromError`` — function
 * components have no hook equivalent. Keep the surface tiny.
 */
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
    this._handleRetry = this._handleRetry.bind(this);
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, errorInfo) {
    // eslint-disable-next-line no-console
    console.error('UI error boundary caught:', error, errorInfo);
  }

  _handleRetry() {
    this.setState({ error: null });
  }

  render() {
    const { error } = this.state;
    if (!error) {
      return this.props.children;
    }
    // Phase 4: page-scoped boundaries pass ``scope`` so each fallback
    // labels which page failed (Player / Library / Cards / Settings)
    // while still letting the user retry that page in isolation. The
    // top-level (unscoped) boundary keeps the original heading and
    // styling so existing behaviour is preserved.
    const { scope } = this.props;
    const testId = scope ? `ui-error-boundary-${scope}` : 'ui-error-boundary';
    const retryTestId = scope
      ? `ui-error-boundary-retry-${scope}`
      : 'ui-error-boundary-retry';
    const heading = scope ? `Error in ${scope}` : 'Something went wrong';
    return (
      <Box sx={{ p: scope ? 2 : 4, maxWidth: 640, mx: 'auto' }}>
        <Alert
          severity="error"
          data-testid={testId}
          action={
            <Button
              color="inherit"
              size="small"
              data-testid={retryTestId}
              onClick={this._handleRetry}
            >
              Retry
            </Button>
          }
        >
          <AlertTitle>{heading}</AlertTitle>
          {error.message || String(error)}
        </Alert>
      </Box>
    );
  }
}

export default ErrorBoundary;
