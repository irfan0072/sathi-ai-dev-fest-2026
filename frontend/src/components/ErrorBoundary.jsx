import { Component } from 'react';
import Icon from './Icon';

/** Keeps one page's crash from blanking the whole console. */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('Page crashed', error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="panel mx-auto max-w-lg">
        <div className="panel-body items-center gap-3 text-center">
          <span className="grid size-12 place-items-center rounded-full bg-error/15 text-error"><Icon name="warning" className="size-6" /></span>
          <h2 className="text-lg font-semibold">This page hit an error</h2>
          <p className="text-sm opacity-70">Other pages still work. Reload to try again; the error is in the browser console.</p>
          <code className="max-w-full truncate rounded bg-base-200 px-2 py-1 text-xs">{String(this.state.error?.message || this.state.error)}</code>
          <button className="btn btn-primary btn-sm" onClick={() => this.setState({ error: null })}>Try again</button>
        </div>
      </div>
    );
  }
}
