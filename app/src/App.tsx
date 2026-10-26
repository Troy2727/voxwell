import { useEffect, useState } from 'react';
import { api } from './api';
import { FEATURES } from './features';

export default function App() {
  const [active, setActive] = useState(FEATURES[0].id);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    api('/api/health').then(() => setOnline(true), () => setOnline(false));
  }, []);

  const { Page } = FEATURES.find((f) => f.id === active)!;

  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">Voxwell</div>
        {FEATURES.map((f) => (
          <button key={f.id} className={f.id === active ? 'nav active' : 'nav'} onClick={() => setActive(f.id)}>
            {f.title}
          </button>
        ))}
        <div className="status">{online === null ? 'Connecting…' : online ? 'Backend online' : 'Backend offline'}</div>
      </nav>
      <main className="content">
        <Page />
      </main>
    </div>
  );
}
