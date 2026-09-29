import React, { useEffect, useState } from 'react';

export const QuizArena = ({ sessionId }) => {
  const [quizzes, setQuizzes] = useState([]);
  const [selected, setSelected] = useState(null);
  const [answers, setAnswers] = useState([]);
  const [hours, setHours] = useState(1);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const loadQuizzes = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`/api/quiz/${sessionId}`);
      if (!response.ok) throw new Error('Unable to load the concept quizzes.');
      const data = await response.json();
      setQuizzes(data.quizzes || []);
      if (data.quizzes?.length) {
        setSelected((current) => data.quizzes.find((quiz) => quiz.concept_id === current?.concept_id) || data.quizzes[0]);
      }
    } catch (loadError) {
      console.error(loadError);
      setError(loadError.message || 'Unable to load quizzes.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadQuizzes(); }, [sessionId]);

  const submitQuiz = async () => {
    if (!selected) return;
    setSubmitting(true);
    setError('');
    try {
      const response = await fetch('/api/quiz/submit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, concept_id: selected.concept_id, answers, hours_per_day: Number(hours) || 1 })
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'The quiz could not be submitted.');
      if (!payload.study_plan) throw new Error('The quiz was scored, but no study plan was returned.');
      setResult(payload);
    } catch (submitError) {
      console.error(submitError);
      setError(submitError.message || 'The quiz could not be submitted. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <div className="rounded-3xl border border-slate-800 bg-slate-900/70 p-8 text-sm text-slate-400">Preparing your concept quizzes…</div>;
  if (error && !quizzes.length) return <div className="rounded-3xl border border-rose-800/60 bg-rose-950/20 p-8 text-center"><h2 className="text-xl font-semibold text-rose-200">Quiz unavailable</h2><p className="mt-2 text-sm text-rose-300/80">{error}</p><button onClick={loadQuizzes} className="mt-4 rounded-xl border border-rose-700 px-4 py-2 text-xs text-rose-200">Retry</button></div>;
  if (!quizzes.length) return <div className="rounded-3xl border border-dashed border-slate-700 bg-slate-900/60 p-10 text-center"><h2 className="text-xl font-semibold text-white">Your quizzes will appear here</h2><p className="mt-2 text-sm text-slate-400">Learn a physics concept in Voice Tutor first, then return here to test your understanding.</p></div>;

  return (
    <div className="space-y-5">
      <div className="rounded-3xl border border-slate-800 bg-slate-900/80 p-6">
        <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-cyan-400">Adaptive concept quiz</p>
        <h1 className="mt-2 text-2xl font-semibold text-white">Test what you understand</h1>
        <p className="mt-2 text-sm text-slate-400">Each quiz is generated from the concept dialogue and your study plan adapts to your score.</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {quizzes.map((quiz) => <button key={quiz.concept_id} onClick={() => { setSelected(quiz); setAnswers([]); setResult(null); }} className={`rounded-full border px-4 py-2 text-xs transition ${selected?.concept_id === quiz.concept_id ? 'border-cyan-500 bg-cyan-950/50 text-cyan-200' : 'border-slate-700 text-slate-400 hover:text-white'}`}>{quiz.topic}</button>)}
      </div>
      {error && <div className="rounded-xl border border-rose-800/60 bg-rose-950/20 px-4 py-3 text-xs text-rose-200">{error}</div>}
      {selected && !result && <div className="space-y-4">
        {selected.questions.map((question, index) => <div key={question.id} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><p className="text-sm font-medium text-white">{index + 1}. {question.question}</p><div className="mt-3 grid gap-2 sm:grid-cols-2">{question.options.map((option, optionIndex) => <button key={option} onClick={() => { const next = [...answers]; next[index] = optionIndex; setAnswers(next); }} className={`rounded-xl border px-3 py-2 text-left text-xs ${answers[index] === optionIndex ? 'border-cyan-500 bg-cyan-950/50 text-cyan-200' : 'border-slate-700 text-slate-400 hover:border-slate-500'}`}>{option}</button>)}</div></div>)}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-950/60 p-4"><label className="text-xs text-slate-400">Daily study time (hours)<input type="number" min="0.25" max="12" step="0.25" value={hours} onChange={(event) => setHours(event.target.value)} className="ml-3 w-20 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-white" /></label><button onClick={submitQuiz} disabled={submitting || !selected.questions.every((_, index) => Number.isInteger(answers[index]))} className="rounded-xl bg-cyan-600 px-5 py-2.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">{submitting ? 'Scoring quiz…' : 'Submit quiz'}</button></div>
      </div>}
      {result && <div className="space-y-4 rounded-3xl border border-cyan-800/50 bg-slate-900/80 p-6"><p className="text-[10px] font-mono uppercase tracking-[0.18em] text-cyan-400">Result</p><h2 className="text-3xl font-semibold text-white">{result.score}/{result.total} <span className="text-base text-slate-400">({result.percentage}%)</span></h2><div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4"><h3 className="font-semibold text-white">{result.study_plan.title}</h3><p className="mt-1 text-sm text-slate-400">{result.study_plan.goal}</p><div className="mt-4 space-y-3">{result.study_plan.schedule?.map((day) => <div key={day.day} className="border-l-2 border-cyan-600 pl-3"><p className="text-xs font-semibold text-cyan-200">Day {day.day} · {day.minutes} minutes · {day.focus}</p><p className="mt-1 text-xs text-slate-300">{day.activity}</p><div className="mt-2 space-y-1">{day.blocks?.map((block, blockIndex) => <p key={blockIndex} className="text-[11px] text-slate-500">{block.minutes} min · {block.task}</p>)}</div><p className="mt-1 text-[11px] text-slate-400">Checkpoint: {day.checkpoint}</p></div>)}</div></div><button onClick={() => { setResult(null); setAnswers([]); }} className="rounded-xl border border-slate-700 px-4 py-2 text-xs text-slate-300 hover:text-white">Retake quiz</button></div>}
    </div>
  );
};
