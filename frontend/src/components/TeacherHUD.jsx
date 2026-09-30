import React, { useState, useEffect } from 'react';
import { BrainCircuit, Activity, CheckCircle2, AlertTriangle, HelpCircle, RefreshCw, FileText, ClipboardCheck, CalendarDays, Trash2 } from 'lucide-react';
import { FormattedMathText } from '../utils/katexHelper';

export const TeacherHUD = ({ sessionId, unitId }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [reportMsg, setReportMsg] = useState('');
  const [clearMsg, setClearMsg] = useState('');

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

  const handleClearPlan = async (attempt) => {
    if (!window.confirm(`Remove the entire ${attempt.topic} quiz and study schedule from the Diagnostic HUD?`)) return;
    try {
      const response = await fetch('/api/quiz/clear-plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, concept_id: attempt.concept_id })
      });
      if (!response.ok) throw new Error('Unable to clear this schedule.');
      setClearMsg(`${attempt.topic} quiz and schedule removed from the HUD.`);
      fetchTeacherData();
      setTimeout(() => setClearMsg(''), 4000);
    } catch (error) {
      setClearMsg(error.message || 'Unable to clear this schedule.');
    }
  };

  const handleClearAllPlans = async () => {
    if (!window.confirm('Remove every quiz result and study schedule from this session? This cannot be undone.')) return;
    try {
      const response = await fetch('/api/quiz/clear-plan', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId })
      });
      if (!response.ok) throw new Error('Unable to clear the schedules.');
      setClearMsg('All quiz results and study schedules were removed from the HUD.');
      fetchTeacherData();
      setTimeout(() => setClearMsg(''), 4000);
    } catch (error) {
      setClearMsg(error.message || 'Unable to clear the schedules.');
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
        {data && data.concept_states && Object.values(data.concept_states).filter((c) => c.total_attempts > 0 || c.recovery_verified || (c.misconceptions_logged && c.misconceptions_logged.length > 0)).map((c) => {
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

      {/* Concept Quiz Results & Adaptive Study Plans */}
      <div className="p-5 bg-slate-900 border border-slate-800 rounded-2xl space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-bold text-slate-100 flex items-center gap-2">
              <ClipboardCheck className="w-4 h-4 text-cyan-400" />
              Concept Quiz Results & Study Plans
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              Quiz evidence is linked to the learned concept and used to create an adaptive plan based on the learner's available study time.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-mono text-cyan-300 bg-cyan-500/10 border border-cyan-500/20 rounded-full px-2 py-1">Default: 1 hr/day</span>
            {data?.quiz_attempts?.some((attempt) => !attempt.study_plan_cleared) && <button type="button" onClick={handleClearAllPlans} className="flex items-center gap-1 rounded-full border border-rose-800/60 px-2 py-1 text-[11px] text-rose-300 hover:bg-rose-950/30"><Trash2 className="w-3 h-3" /> Clear all schedules</button>}
          </div>
        </div>
        {clearMsg && <div className="p-2.5 bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs rounded-lg">{clearMsg}</div>}

        {data && data.quiz_attempts && data.quiz_attempts.length > 0 ? (
          <div className="space-y-3">
            {data.quiz_attempts.map((attempt, idx) => {
              const percentage = Math.round((attempt.score / Math.max(attempt.total, 1)) * 100);
              const schedule = attempt.study_plan && Array.isArray(attempt.study_plan.schedule)
                ? attempt.study_plan.schedule
                : [];
              return (
                <div key={`${attempt.concept_id}-${attempt.created_at}-${idx}`} className="p-4 bg-slate-950 border border-slate-800 rounded-xl space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h4 className="text-sm font-semibold text-slate-100">{attempt.topic}</h4>
                      <p className="text-[11px] text-slate-500 font-mono mt-1">
                        {attempt.created_at ? new Date(attempt.created_at).toLocaleString() : 'Recent attempt'} • {attempt.hours_per_day} hr/day
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className={`text-sm font-bold px-2.5 py-1 rounded-lg border ${percentage >= 70 ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30' : 'text-amber-300 bg-amber-500/10 border-amber-500/30'}`}>
                        {attempt.score}/{attempt.total} ({percentage}%)
                      </div>
                      {!attempt.study_plan_cleared && <button type="button" onClick={() => handleClearPlan(attempt)} className="flex items-center gap-1 rounded-lg border border-rose-800/60 px-2 py-1 text-[11px] text-rose-300 hover:bg-rose-950/30" title="Clear this study schedule"><Trash2 className="w-3 h-3" /> Clear schedule</button>}
                    </div>
                  </div>

                  {attempt.study_plan && attempt.study_plan.schedule?.length > 0 ? (
                    <div className="p-3 bg-teal-950/20 border border-teal-900/40 rounded-lg">
                      <div className="flex items-center gap-2 text-teal-300 text-xs font-semibold">
                        <CalendarDays className="w-3.5 h-3.5" />
                        {attempt.study_plan.title || 'Adaptive study plan'}
                        {attempt.study_plan.duration_days ? ` • ${attempt.study_plan.duration_days} days` : ''}
                      </div>
                      {attempt.study_plan.goal && <p className="text-xs text-slate-300 mt-1">{attempt.study_plan.goal}</p>}
                      {schedule.length > 0 && (
                        <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
                          {schedule.slice(0, 6).map((day, dayIndex) => {
                            const completed = (attempt.completed_days || []).includes(day.day || dayIndex + 1);
                            return <div key={`${day.day || dayIndex}-${dayIndex}`} className={`p-2 bg-slate-950/70 border rounded-lg text-[11px] ${completed ? 'border-emerald-500/40' : 'border-slate-800'}`}>
                              <div className={`font-mono flex items-center gap-1 ${completed ? 'text-emerald-300' : 'text-cyan-300'}`}>{completed && <CheckCircle2 className="w-3 h-3" />}Day {day.day || dayIndex + 1} • {day.minutes || 60} min{completed ? ' • Completed' : ''}</div>
                              <div className="text-slate-200 mt-1">{day.focus || 'Concept practice'}</div>
                              {day.checkpoint && <div className="text-slate-500 mt-1">Checkpoint: {day.checkpoint}</div>}
                            </div>;
                          })}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="p-3 rounded-lg border border-dashed border-slate-700 text-xs text-slate-500">Schedule cleared. The quiz score remains available as diagnostic evidence.</div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-center py-6 text-slate-500 text-xs font-mono border border-dashed border-slate-800 rounded-xl">
            Complete a concept quiz in the Quiz tab to add score evidence and an adaptive study plan here.
          </div>
        )}
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
            data.conversation_history.map((turn, idx) => (turn.type === 'TEACHER_OVERRIDE' || turn.timestamp === 'TEACHER_OVERRIDE') ? (
              <div key={idx} className="p-3 bg-amber-950/20 border border-amber-800/40 rounded-xl text-xs space-y-1">
                <div className="font-mono text-amber-300">
                  Teacher override • {turn.timestamp && turn.timestamp !== 'TEACHER_OVERRIDE' ? new Date(turn.timestamp).toLocaleTimeString() : 'Recorded'}
                </div>
                <p className="text-slate-200">
                  Mastery of <span className="font-mono">{turn.concept_id}</span> set to {Math.round((turn.new_mastery || 0) * 100)}%
                  {turn.teacher_note ? ` — ${turn.teacher_note}` : ''}
                </p>
              </div>
            ) : (
              <div key={idx} className="p-3 bg-slate-950 border border-slate-800/80 rounded-xl space-y-2">
                <div className="flex items-center justify-between text-xs text-slate-400">
                  <span className="font-mono">Turn #{idx + 1} • {turn.timestamp ? new Date(turn.timestamp).toLocaleTimeString() : 'Recent'}</span>
                  <div className="flex items-center gap-2">
                    {turn.graded && turn.reasoning_soundness >= 0.85 && !turn.is_lucky_guess ? (
                      <span className="px-2 py-0.5 rounded text-xs bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">Sound Reasoning</span>
                    ) : turn.category && getCategoryBadge(turn.category)}
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

    </div>
  );
};
