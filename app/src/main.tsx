import { Component, StrictMode, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { Button } from '@/components/ui/button';
import { applyTheme } from './lib/theme';
import './styles.css';

applyTheme(); // before the first paint, so there is no light flash

/** Without this, a crash while drawing a page removes everything and leaves a blank screen. */
class CrashMessage extends Component<{ children: ReactNode }, { crashed: boolean }> {
  state = { crashed: false };

  static getDerivedStateFromError() {
    return { crashed: true };
  }

  render() {
    if (!this.state.crashed) return this.props.children;
    return (
      <div role="alert" className="flex flex-col items-center gap-4 p-8 text-center">
        <p>Something went wrong and Voxwell couldn't show this page.</p>
        <Button onClick={() => window.location.reload()}>Reload</Button>
      </div>
    );
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <CrashMessage>
      <App />
    </CrashMessage>
  </StrictMode>,
);
