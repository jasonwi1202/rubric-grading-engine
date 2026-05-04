"use client";

/**
 * ErrorBoundary — reusable React error boundary for isolating rendering failures.
 *
 * Catches JavaScript errors thrown during the render phase in any descendant
 * component tree and replaces the failed subtree with a predictable fallback
 * instead of crashing the entire page.
 *
 * Usage:
 *   <ErrorBoundary>
 *     <SomeComplexPanel />
 *   </ErrorBoundary>
 *
 *   // Static fallback (no reset button):
 *   <ErrorBoundary fallback={<p>Custom fallback</p>}>
 *     <SomeComplexPanel />
 *   </ErrorBoundary>
 *
 *   // Render-prop fallback — receives resetErrorBoundary so the custom UI
 *   // can expose its own reset action:
 *   <ErrorBoundary fallbackRender={({ resetErrorBoundary }) => (
 *     <button onClick={resetErrorBoundary}>Retry</button>
 *   )}>
 *     <SomeComplexPanel />
 *   </ErrorBoundary>
 *
 * Security:
 *   - `error.message` is never logged or displayed — it can contain student PII
 *     if an unexpected value ends up in a template literal inside a component.
 *   - In development mode only, `error.name` (the error type) and the component
 *     stack are logged to the console to aid debugging without leaking runtime
 *     values.
 *   - The fallback UI contains no reference to the original error.
 */

import { Component, type ReactNode, type ErrorInfo } from "react";

// ---------------------------------------------------------------------------
// Props & state
// ---------------------------------------------------------------------------

interface ErrorBoundaryProps {
  /** Content to render when no error has occurred. */
  children: ReactNode;
  /**
   * Optional static fallback node.  When omitted the default "something went
   * wrong" panel is rendered.  Cannot itself trigger a boundary reset — use
   * `fallbackRender` when the custom UI needs a reset action.
   */
  fallback?: ReactNode;
  /**
   * Render-prop fallback that receives `{ resetErrorBoundary }`.  Takes
   * precedence over `fallback` when both are provided.  Use this when the
   * custom fallback needs to expose a reset action to the user.
   */
  fallbackRender?: (props: { resetErrorBoundary: () => void }) => ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

// ---------------------------------------------------------------------------
// Default fallback UI
// ---------------------------------------------------------------------------

function DefaultFallback({ onReset }: { onReset: () => void }) {
  return (
    <div
      role="alert"
      className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm"
    >
      <p className="font-medium text-red-700">
        Something went wrong loading this section.
      </p>
      <p className="mt-1 text-red-600">
        Try refreshing the page. If the problem persists, contact support.
      </p>
      <button
        type="button"
        onClick={onReset}
        className="mt-3 rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1"
      >
        Try again
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error boundary class component
// ---------------------------------------------------------------------------

export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Log only the error name (type), never the message or stack values that
    // could contain student data embedded in template-literal strings.
    if (process.env.NODE_ENV === "development") {
      // eslint-disable-next-line no-console
      console.error(
        "[ErrorBoundary] Caught rendering error:",
        error.name,
        info.componentStack,
      );
    }
  }

  private handleReset = () => {
    this.setState({ hasError: false });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallbackRender !== undefined) {
        return this.props.fallbackRender({
          resetErrorBoundary: this.handleReset,
        });
      }
      if (this.props.fallback !== undefined) {
        return this.props.fallback;
      }
      return <DefaultFallback onReset={this.handleReset} />;
    }

    return this.props.children;
  }
}
