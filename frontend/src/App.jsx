import React, { useEffect, useState } from 'react';
import { MinimalVoiceStudio } from './components/MinimalVoiceStudio';
import { TeacherHUD } from './components/TeacherHUD';
import { WebGroundingViewer } from './components/WebGroundingViewer';

export default function App() {
  const [activeTab, setActiveTab] = useState('voice'); // 'voice' | 'teacher' | 'grounding'
  const [sessionId] = useState(() => {
    const storageKey = 'misconceptionos-learner-session';
    const existingId = window.localStorage.getItem(storageKey);
    if (existingId) return existingId;
    const newId = `learner-${crypto.randomUUID()}`;
    window.localStorage.setItem(storageKey, newId);
    return newId;
  });
  const [historyOpen, setHistoryOpen] = useState(false);
  const [conceptHistory, setConceptHistory] = useState({});

  const refreshHistory = async () => {
    try {
      const response = await fetch(`/api/teacher/concept-conversations/${sessionId}`);
      if (!response.ok) return;
      const data = await response.json();
      setConceptHistory(data.conversations || {});
    } catch (error) {
      console.warn('Unable to load conversation history:', error);
    }
  };

  useEffect(() => {
    if (historyOpen) refreshHistory();
  }, [historyOpen, sessionId]);

  return (
    <div className="min-h-screen bg-black text-slate-100 flex flex-col justify-between selection:bg-teal-500 selection:text-white font-['Plus_Jakarta_Sans',sans-serif]">
      {/* Sleek Minimal Top Navigation (ChatGPT Style) */}
      <header className="px-6 py-4 flex items-center justify-between z-50">
        {/* Left: Minimal Brand */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setHistoryOpen((open) => !open)}
            aria-expanded={historyOpen}
            aria-label={historyOpen ? 'Close conversation history' : 'Open conversation history'}
            className="text-sm font-semibold tracking-tight text-white hover:text-cyan-300 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 rounded"
          >
            MisconceptionOS
          </button>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-900 text-slate-400 border border-slate-800">
            Socratic AI
          </span>
        </div>

        {/* Right: Clean Switchers */}
        <div className="flex items-center gap-1.5 p-1 bg-slate-900/80 rounded-full border border-slate-800 backdrop-blur-md">
          <button
            onClick={() => setActiveTab('voice')}
            className={`px-3.5 py-1 rounded-full text-xs font-medium transition ${
              activeTab === 'voice'
                ? 'bg-slate-800 text-white shadow'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Voice Tutor
          </button>
          <button
            onClick={() => setActiveTab('teacher')}
            className={`px-3.5 py-1 rounded-full text-xs font-medium transition ${
              activeTab === 'teacher'
                ? 'bg-slate-800 text-white shadow'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Diagnostic HUD
          </button>
          <button
            onClick={() => setActiveTab('grounding')}
            className={`px-3.5 py-1 rounded-full text-xs font-medium transition ${
              activeTab === 'grounding'
                ? 'bg-cyan-950/60 text-cyan-300 border border-cyan-800/40 shadow'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Web Grounding
          </button>
        </div>
      </header>

      {/* Session history drawer */}
      <aside
        aria-hidden={!historyOpen}
        className={`fixed top-16 bottom-0 left-0 z-40 w-80 max-w-[88vw] border-r border-slate-800 bg-[#080b14] shadow-2xl transition-transform duration-300 ease-out ${
          historyOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
          <div>
            <p className="text-sm font-semibold text-white">History</p>
            <p className="mt-1 text-sm text-slate-300">This session</p>
          </div>
          <button
            type="button"
            onClick={() => setHistoryOpen(false)}
            aria-label="Close conversation history"
            className="rounded-full p-2 text-slate-400 transition hover:bg-slate-800 hover:text-white"
          >
            ×
          </button>
        </div>
        <div className="h-[calc(100%-73px)] overflow-y-auto px-4 py-4">
          {Object.keys(conceptHistory).length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-800 px-3 py-4 text-xs leading-5 text-slate-500">
              Physics concepts you explore will appear here and remain available when you return.
            </p>
          ) : (
            <div className="space-y-3">
              {Object.entries(conceptHistory).map(([conceptId, turns]) => {
                const latestTurn = turns[turns.length - 1];
                const topic = latestTurn?.topic || conceptId.replaceAll('_', ' ');
                return (
                  <div key={conceptId} className="rounded-lg border border-slate-800 bg-slate-950/70 p-3">
                    <p className="text-sm font-semibold capitalize text-cyan-200">{topic}</p>
                    <p className="mt-1 text-[10px] font-mono uppercase tracking-wide text-slate-500">
                      {turns.length} {turns.length === 1 ? 'conversation' : 'conversations'}
                    </p>
                    <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-400">{latestTurn?.user}</p>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </aside>

      {historyOpen && (
        <button
          type="button"
          aria-label="Close conversation history"
          onClick={() => setHistoryOpen(false)}
          className="fixed inset-0 z-30 bg-black/40"
        />
      )}

      {/* Main Canvas */}
      <main className="flex-1 flex flex-col justify-center px-4">
        {activeTab === 'voice' && (
          <MinimalVoiceStudio
            sessionId={sessionId}
            onStateUpdate={() => {
              if (historyOpen) refreshHistory();
            }}
          />
        )}

        {activeTab === 'teacher' && (
          <div className="max-w-6xl mx-auto w-full py-6">
            <TeacherHUD
              sessionId={sessionId}
              unitId="physics_mechanics"
            />
          </div>
        )}

        {activeTab === 'grounding' && (
          <div className="max-w-4xl mx-auto w-full py-6">
            <WebGroundingViewer />
          </div>
        )}
      </main>

      {/* Minimal Footer */}
      <footer className="py-3 text-center text-[10px] font-mono text-slate-600">
        Pure Voice Interaction • Click the Silver Orb to speak • Socratic Anti-Leakage Guard Active
      </footer>
    </div>
  );
}
