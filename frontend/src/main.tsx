import { Component, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import "./design-system/tokens.css";
import "./styles.css";

/** One minimal boundary: an uncaught render error must not blank the page silently. */
class ErrorBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

const el = document.getElementById("root");
if (!el) throw new Error("#root missing from index.html");
createRoot(el).render(
  <ErrorBoundary fallback={<p style={{ padding: 24 }}>Unexpected error. Reload the page.</p>}>
    <App />
  </ErrorBoundary>,
);
