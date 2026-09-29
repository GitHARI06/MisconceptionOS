import React, { useEffect, useState } from 'react';
import { MinimalVoiceStudio } from './components/MinimalVoiceStudio';
import { TeacherHUD } from './components/TeacherHUD';
import { WebGroundingViewer } from './components/WebGroundingViewer';
import { QuizArena } from './components/QuizArena';

export default function App() {
  const [activeTab, setActiveTab] = useState('voice'); // 'voice' | 'teacher' | 'grounding' | 'quiz'
  const [sessionId, setSessionId] = useState(() => {
    const storageKey = 'misconceptionos-learner-session';
    const existingId = window.localStorage.getItem(storageKey);
    if (existingId) return existingId;
    const newId = `learner-${crypto.randomUUID()}`;
    window.localStorage.setItem(storageKey, newId);
    return newId;
  });
  const [historyOpen, setHistoryOpen] = useState(false);
  const [conceptHistory, setConceptHistory] = useState({});
  const [account, setAccount] = useState(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const [authMode, setAuthMode] = useState('login');
  const [authForm, setAuthForm] = useState({ username: '', email: '', password: '', class_level: '' });
  const [authError, setAuthError] = useState('');
  const [authBusy, setAuthBusy] = useState(false);

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

  useEffect(() => {
    const token = window.localStorage.getItem('misconceptionos-auth-token');
    if (!token) return;
    fetch('/api/auth/me', { headers: { Authorization: `Bearer ${token}` } })
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((data) => {
        setAccount(data.user);
        setSessionId(`account-${data.user.id}`);
      })
      .catch(() => window.localStorage.removeItem('misconceptionos-auth-token'));
  }, []);

  const submitAuth = async (event) => {
    event.preventDefault();
    setAuthBusy(true);
    setAuthError('');
    try {
      const endpoint = authMode === 'login' ? '/api/auth/login' : '/api/auth/register';
      const payload = authMode === 'login'
        ? { identity: authForm.username || authForm.email, password: authForm.password }
        : authForm;
      const response = await fetch(endpoint, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Unable to authenticate.');
      window.localStorage.setItem('misconceptionos-auth-token', data.token);
      setAccount(data.user);
      setSessionId(`account-${data.user.id}`);
      setAccountOpen(false);
      setAuthForm({ username: '', email: '', password: '', class_level: '' });
    } catch (error) {
      setAuthError(error.message);
    } finally {
      setAuthBusy(false);
    }
  };

  const signOut = () => {
    window.localStorage.removeItem('misconceptionos-auth-token');
    const anonymousId = `learner-${crypto.randomUUID()}`;
    window.localStorage.setItem('misconceptionos-learner-session', anonymousId);
    setAccount(null);
    setSessionId(anonymousId);
    setAccountOpen(false);
  };

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
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => { setAuthError(''); setAccountOpen(true); }}
            className="rounded-full border border-slate-800 bg-slate-900/80 px-3 py-1.5 text-xs text-slate-300 transition hover:border-cyan-700 hover:text-white"
          >
            {account ? `${account.username} · ${account.class_level}` : 'Student account'}
          </button>
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
          <button
            onClick={() => setActiveTab('quiz')}
            className={`px-3.5 py-1 rounded-full text-xs font-medium transition ${
              activeTab === 'quiz'
                ? 'bg-emerald-950/60 text-emerald-300 border border-emerald-800/40 shadow'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Concept Quiz
          </button>
          </div>
        </div>
      </header>

      {accountOpen && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <form onSubmit={submitAuth} className="w-full max-w-md space-y-4 rounded-3xl border border-slate-800 bg-[#0b1020] p-6 text-left shadow-2xl">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-cyan-400">Student account</p>
                <h2 className="mt-1 text-xl font-semibold text-white">{authMode === 'login' ? 'Welcome back' : 'Create your account'}</h2>
              </div>
              <button type="button" onClick={() => setAccountOpen(false)} className="text-xl text-slate-400 hover:text-white">×</button>
            </div>
            {account ? (
              <div className="space-y-4">
                <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-300">
                  <p className="font-semibold text-white">{account.username}</p>
                  <p className="mt-1">{account.email}</p>
                  <p className="mt-1 text-cyan-300">{account.class_level}</p>
                </div>
                <button type="button" onClick={signOut} className="w-full rounded-xl border border-rose-900/70 px-4 py-2.5 text-sm text-rose-300 hover:bg-rose-950/30">Sign out</button>
              </div>
            ) : <>
            {authMode === 'register' && (
              <>
                <input required minLength={2} value={authForm.username} onChange={(e) => setAuthForm({ ...authForm, username: e.target.value })} placeholder="Username" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-white outline-none focus:border-cyan-500" />
                <input required type="email" value={authForm.email} onChange={(e) => setAuthForm({ ...authForm, email: e.target.value })} placeholder="Email address" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-white outline-none focus:border-cyan-500" />
                <input required value={authForm.class_level} onChange={(e) => setAuthForm({ ...authForm, class_level: e.target.value })} placeholder="Your class (e.g. Class 11)" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-white outline-none focus:border-cyan-500" />
              </>
            )}
            {authMode === 'login' && <input required value={authForm.username} onChange={(e) => setAuthForm({ ...authForm, username: e.target.value })} placeholder="Username or email address" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-white outline-none focus:border-cyan-500" />}
            <input required minLength={8} type="password" value={authForm.password} onChange={(e) => setAuthForm({ ...authForm, password: e.target.value })} placeholder="Password (8+ characters)" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-white outline-none focus:border-cyan-500" />
            {authError && <p className="text-xs text-rose-300">{authError}</p>}
            <button disabled={authBusy} className="w-full rounded-xl bg-cyan-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:opacity-50">{authBusy ? 'Please wait…' : authMode === 'login' ? 'Sign in' : 'Create account'}</button>
            <button type="button" onClick={() => { setAuthMode(authMode === 'login' ? 'register' : 'login'); setAuthError(''); }} className="w-full text-xs text-slate-400 hover:text-cyan-300">{authMode === 'login' ? 'New student? Create an account' : 'Already have an account? Sign in'}</button>
            </>}
          </form>
        </div>
      )}

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

        {activeTab === 'quiz' && (
          <div className="max-w-5xl mx-auto w-full py-6">
            <QuizArena sessionId={sessionId} />
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
