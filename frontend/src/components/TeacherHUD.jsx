import React, { useState, useEffect } from 'react';
import { ShieldAlert, BrainCircuit, Activity, CheckCircle2, AlertTriangle, HelpCircle, RefreshCw, Send, FileText } from 'lucide-react';
import { FormattedMathText } from '../utils/katexHelper';

export const TeacherHUD = ({ sessionId, unitId }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [overrideConcept, setOverrideConcept] = useState('');
  const [overrideValue, setOverrideValue] = useState(0.85);
  const [overrideNote, setOverrideNote] = useState('');
  const [overrideMsg, setOverrideMsg] = useState('');
  const [reportMsg, setReportMsg] = useState('');

  const fetchTeacherData = async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/teacher/learner-state/${sessionId}`);
      if (res.ok) {
        const json = await res.json();
        setData(json);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleExtractReport = async () => {
    if (!data) return;
    try {
      const response = await fetch(`/api/teacher/report/${encodeURIComponent(sessionId)}`);
      if (!response.ok) throw new Error('Report generation failed');
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `learnable-physics-evidence-${data.session_id || 'session'}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setReportMsg('PDF evidence report downloaded successfully.');
      setTimeout(() => setReportMsg(''), 4000);
    } catch (error) {
      console.error(error);
      setReportMsg('Unable to generate the PDF report. Please refresh and try again.');
      setTimeout(() => setReportMsg(''), 5000);
    }
  };

  useEffect(() => {
    fetchTeacherData();
    const interval = setInterval(fetchTeacherData, 5000);
    return () => clearInterval(interval);
  }, [sessionId]);

  const handleOverrideSubmit = async (e) => {
    e.preventDefault();
    if (!overrideConcept) return;
    try {
      const res = await fetch('/api/teacher/override', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          concept_id: overrideConcept,
          override_mastery_prob: parseFloat(overrideValue),
          teacher_note: overrideNote || "Teacher manual calibration"
        })
      });
      if (res.ok) {
        setOverrideMsg('Override recorded successfully in audit trail!');
        fetchTeacherData();
        setTimeout(() => setOverrideMsg(''), 4000);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const getCategoryBadge = (category) => {
    switch (category) {
      case 'wrong_rule_definition':
        return <span className="px-2 py-0.5 rounded text-xs bg-rose-500/20 text-rose-300 border border-rose-500/30">Wrong Rule / Definition</span>;
      case 'overgeneralization':
        return <span className="px-2 py-0.5 rounded text-xs bg-amber-500/20 text-amber-300 border border-amber-500/30">Overgeneralization</span>;
      case 'missing_prerequisite':
        return <span className="px-2 py-0.5 rounded text-xs bg-purple-500/20 text-purple-300 border border-purple-500/30">Missing Prerequisite</span>;
      case 'procedural_error':
        return <span className="px-2 py-0.5 rounded text-xs bg-blue-500/20 text-blue-300 border border-blue-500/30">Procedural Error</span>;
      case 'calculation_slip':
        return <span className="px-2 py-0.5 rounded text-xs bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">Calculation Slip</span>;
      default:
        return <span className="px-2 py-0.5 rounded text-xs bg-slate-500/20 text-slate-300 border border-slate-500/30">Insufficient Evidence</span>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex items-center justify-between p-4 bg-slate-900 border border-slate-800 rounded-2xl">
        <div className="flex items-center space-x-3">
          <div className="p-2.5 bg-teal-500/10 text-teal-400 rounded-xl border border-teal-500/20">
            <BrainCircuit className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              Teacher Diagnostic & Evidence HUD
              <span className="text-xs px-2 py-0.5 rounded-full bg-teal-500/20 text-teal-300 border border-teal-500/30">Real-time Telemetry</span>
            </h2>
            <p className="text-xs text-slate-400">
              Live cognitive state tracking, misconception frequency analysis, and Bayesian knowledge tracing.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExtractReport}
            disabled={!data}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-teal-600 hover:bg-teal-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-lg border border-teal-500/40 transition"
          >
            <FileText className="w-3.5 h-3.5" />
            Extract Report
          </button>
          <button
            onClick={fetchTeacherData}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg border border-slate-700 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {reportMsg && (
        <div className="p-3 bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-xs rounded-xl font-mono">
          {reportMsg}
        </div>
      )}

      {/* Grid: Knowledge Components Mastery */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {data && data.concept_states && Object.values(data.concept_states).map((c) => {
          const masteryPct = Math.round(c.mastery_prob * 100);
          return (
            <div key={c.concept_id} className="p-4 bg-slate-900/90 border border-slate-800 rounded-xl space-y-3">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-slate-100">{c.concept_name}</h3>
                  <p className="text-xs text-slate-400 font-mono">ID: {c.concept_id}</p>
                </div>
                {c.recovery_verified ? (
                  <span className="flex items-center text-xs font-medium text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/30">
                    <CheckCircle2 className="w-3 h-3 mr-1" /> Verified
                  </span>
                ) : (
                  <span className="text-xs text-slate-400">Attempts: {c.total_attempts}</span>
                )}
              </div>

              {/* Progress Bar */}
              <div>
                <div className="flex justify-between text-xs mb-1 font-mono">
                  <span className="text-slate-400">Estimated Mastery P(L)</span>
                  <span className={masteryPct >= 80 ? "text-emerald-400 font-bold" : masteryPct >= 50 ? "text-amber-400" : "text-rose-400"}>
                    {masteryPct}%
                  </span>
                </div>
                <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all duration-500 ${
                      masteryPct >= 80 ? "bg-emerald-500" : masteryPct >= 50 ? "bg-amber-500" : "bg-rose-500"
                    }`}
                    style={{ width: `${masteryPct}%` }}
                  />
                </div>
              </div>

              {/* Misconception tags */}
              {c.misconceptions_logged && c.misconceptions_logged.length > 0 && (
                <div className="pt-2 border-t border-slate-800/80">
                  <span className="text-xs text-rose-300/80 font-mono block mb-1">Logged Misconceptions:</span>
                  <div className="flex flex-wrap gap-1">
                    {c.misconceptions_logged.map((m, idx) => (
                      <span key={idx} className="px-1.5 py-0.5 bg-rose-950/60 border border-rose-800/60 text-rose-300 text-[10px] rounded font-mono">
                        {m}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Evidence-Backed Diagnostic History Timeline */}
      <div className="p-5 bg-slate-900 border border-slate-800 rounded-2xl space-y-4">
        <h3 className="text-base font-bold text-slate-100 flex items-center gap-2">
          <Activity className="w-4 h-4 text-teal-400" />
          Evidence-Backed Diagnostic Audit Log
        </h3>
        <p className="text-xs text-slate-400">
          Concise pedagogical evidence derived from learner free-response reasoning (No hidden chain-of-thought).
        </p>

        <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
          {data && data.conversation_history && data.conversation_history.length > 0 ? (
            data.conversation_history.map((turn, idx) => (
              <div key={idx} className="p-3 bg-slate-950 border border-slate-800/80 rounded-xl space-y-2">
                <div className="flex items-center justify-between text-xs text-slate-400">
                  <span className="font-mono">Turn #{idx + 1} • {turn.timestamp ? new Date(turn.timestamp).toLocaleTimeString() : 'Recent'}</span>
                  <div className="flex items-center gap-2">
                    {turn.category && getCategoryBadge(turn.category)}
                    <span className="px-2 py-0.5 rounded text-xs bg-slate-800 text-teal-300 border border-slate-700 font-mono">
                      Tier: {turn.tier}
                    </span>
                  </div>
                </div>

                <div className="text-xs bg-slate-900/60 p-2.5 rounded-lg border border-slate-800">
                  <span className="text-slate-400 font-semibold block mb-1">Learner Submission:</span>
                  <span className="text-slate-200 italic font-mono">"{turn.user}"</span>
                </div>

                <div className="text-xs p-2.5 bg-teal-950/20 border border-teal-900/40 rounded-lg">
                  <span className="text-teal-400 font-semibold block mb-1">Pedagogical Evidence:</span>
                  <p className="text-slate-300">{turn.evidence}</p>
                  {turn.is_lucky_guess && (
                    <span className="mt-1 inline-block text-[11px] font-bold text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/30">
                      ⚠️ Lucky Guess Flag: Correct Answer arrived via Flawed Reasoning!
                    </span>
                  )}
                </div>
              </div>
            ))
          ) : (
            <div className="text-center py-8 text-slate-500 text-xs font-mono">
              No learner interactions logged yet in this session. Start speaking or typing in Student Mode!
            </div>
          )}
        </div>
      </div>

      {/* Teacher Calibration & Override Panel */}
      <div className="p-5 bg-slate-900 border border-slate-800 rounded-2xl space-y-3">
        <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-amber-400" />
          Teacher Knowledge Calibration & Manual Override
        </h3>
        <p className="text-xs text-slate-400">
          Teachers can manually calibrate a student's concept mastery or log custom clinical observations.
        </p>

        {overrideMsg && (
          <div className="p-2.5 bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-xs rounded-lg font-mono">
            {overrideMsg}
          </div>
        )}

        <form onSubmit={handleOverrideSubmit} className="grid grid-cols-1 md:grid-cols-4 gap-3 pt-2">
          <div>
            <label className="block text-[11px] font-mono text-slate-400 mb-1">Concept</label>
            <select
              value={overrideConcept}
              onChange={(e) => setOverrideConcept(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 text-xs text-slate-200 rounded-lg p-2 focus:ring-1 focus:ring-teal-500 focus:outline-none"
            >
              <option value="">Select Concept...</option>
              {data && data.concept_states && Object.values(data.concept_states).map(c => (
                <option key={c.concept_id} value={c.concept_id}>{c.concept_name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-mono text-slate-400 mb-1">Calibrated Mastery (0.0 - 1.0)</label>
            <input
              type="number"
              min="0"
              max="1"
              step="0.05"
              value={overrideValue}
              onChange={(e) => setOverrideValue(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 text-xs text-slate-200 rounded-lg p-2 focus:ring-1 focus:ring-teal-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-[11px] font-mono text-slate-400 mb-1">Teacher Note / Rationale</label>
            <input
              type="text"
              placeholder="e.g. Oral exam showed sound intuition"
              value={overrideNote}
              onChange={(e) => setOverrideNote(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 text-xs text-slate-200 rounded-lg p-2 focus:ring-1 focus:ring-teal-500 focus:outline-none"
            />
          </div>

          <div className="flex items-end">
            <button
              type="submit"
              className="w-full bg-teal-600 hover:bg-teal-500 text-white font-semibold text-xs py-2.5 px-4 rounded-lg flex items-center justify-center gap-1.5 transition"
            >
              <Send className="w-3.5 h-3.5" />
              Save Override
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
