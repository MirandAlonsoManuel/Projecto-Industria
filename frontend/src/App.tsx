import { useState } from 'react';
import Header, { type AppView } from './components/Header';
import MainPanel from './components/MainPanel/MainPanel';
import { InferencePanel } from './components/InferencePanel/InferencePanel';
import './App.css';

function App() {
  const [view, setView] = useState<AppView>('monitor');

  return (
    <>
      <Header view={view} onViewChange={setView} />
      {view === 'monitor' ? <MainPanel /> : <InferencePanel />}
    </>
  );
}

export default App;
