import React, { useState } from 'react';
import { MinimalVoiceStudio } from './components/MinimalVoiceStudio';
import { TeacherHUD } from './components/TeacherHUD';
import { StressTestArena } from './components/StressTestArena';
import { WebGroundingViewer } from './components/WebGroundingViewer';

export default function App() {
  const [activeTab, setActiveTab] = useState('voice'); // 'voice' | 'teacher' | 'judge' | 'grounding'
  const [sessionId, setSessionId] = useState(() => 'learner-' + Math.floor(1000 + Math.random() * 9000));

  return (
    <div className="min-h-screen bg-black text-slate-100 flex flex-col justify-between selection:bg-teal-500 selection:text-white font-['Plus_Jakarta_Sans',sans-serif]">
      {/* Sleek Minimal Top Navigation (ChatGPT Style) */}
      <header className="px-6 py-4 flex items-center justify-between z-30">
        {/* Left: Minimal Brand */}
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold tracking-tight text-white">
            MisconceptionOS
          </span>
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
            onClick={() => setActiveTab('judge')}
            className={`px-3.5 py-1 rounded-full text-xs font-medium transition ${
              activeTab === 'judge'
                ? 'bg-rose-950/60 text-rose-300 border border-rose-800/40 shadow'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Judge Arena
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

      {/* Main Canvas */}
      <main className="flex-1 flex flex-col justify-center px-4">
        {activeTab === 'voice' && (
          <MinimalVoiceStudio
            sessionId={sessionId}
            onStateUpdate={() => {}}
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

        {activeTab === 'judge' && (
          <div className="max-w-6xl mx-auto w-full py-6">
            <StressTestArena />
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
