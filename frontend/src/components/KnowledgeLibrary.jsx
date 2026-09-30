import React, { useEffect, useRef, useState } from 'react';
import { X, UploadCloud, FileText, Trash2, Loader2, ClipboardPaste, CheckCircle2, AlertTriangle, BookOpen } from 'lucide-react';

const ACCEPT = '.pdf,.txt,.md,.markdown,application/pdf,text/plain,text/markdown';

const formatWhen = (value) => {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
};

// Upload PDFs / text notes into the tutor's knowledge base, and manage them.
export const KnowledgeLibrary = ({ open, onClose }) => {
  const [documents, setDocuments] = useState([]);
  const [meta, setMeta] = useState({ max_upload_mb: 20 });
  const [loading, setLoading] = useState(false);
  const [queue, setQueue] = useState([]);           // [{name, status: 'uploading'|'done'|'error', message}]
  const [dragging, setDragging] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteTitle, setPasteTitle] = useState('');
  const [pasteText, setPasteText] = useState('');
  const [pasteBusy, setPasteBusy] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef(null);
  const dialogRef = useRef(null);

  const load = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/documents');
      if (!response.ok) throw new Error('Could not load your library.');
      const data = await response.json();
      setDocuments(data.documents || []);
      setMeta(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return undefined;
    setError('');
    load();
    dialogRef.current?.focus();
    const onKey = (event) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  // Semantic indexing finishes in the background: refresh until it is done.
  useEffect(() => {
    if (!open || !documents.some((doc) => !doc.embedded)) return undefined;
    const timer = window.setTimeout(load, 4000);
    return () => window.clearTimeout(timer);
  }, [open, documents]);

  const updateQueue = (name, patch) => setQueue((items) => items.map((item) => (item.name === name ? { ...item, ...patch } : item)));

  const uploadFiles = async (fileList) => {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    setError('');
    setQueue((items) => [...files.map((f) => ({ name: f.name, status: 'uploading', message: '' })), ...items].slice(0, 8));
    const limit = (meta.max_upload_mb || 20) * 1024 * 1024;
    for (const file of files) {
      if (!/\.(pdf|txt|md|markdown)$/i.test(file.name)) {
        updateQueue(file.name, { status: 'error', message: 'Only PDF, TXT and Markdown files can be added.' });
        continue;
      }
      if (file.size > limit) {
        updateQueue(file.name, { status: 'error', message: `Larger than ${meta.max_upload_mb || 20} MB.` });
        continue;
      }
      const form = new FormData();
      form.append('file', file);
      try {
        const response = await fetch('/api/documents', { method: 'POST', body: form });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `Upload failed (${response.status}).`);
        const doc = data.document;
        updateQueue(file.name, {
          status: 'done',
          message: doc.duplicate ? 'Already in your library.' : `${doc.pages} page${doc.pages === 1 ? '' : 's'} · ${doc.chunk_count} passages indexed`,
        });
      } catch (err) {
        updateQueue(file.name, { status: 'error', message: err.message });
      }
    }
    if (inputRef.current) inputRef.current.value = '';
    load();
  };

  const submitPaste = async (event) => {
    event.preventDefault();
    if (!pasteText.trim()) return;
    setPasteBusy(true);
    setError('');
    try {
      const response = await fetch('/api/documents/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: pasteTitle, text: pasteText }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Could not save the text.');
      setPasteText('');
      setPasteTitle('');
      setPasteOpen(false);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setPasteBusy(false);
    }
  };

  const remove = async (doc) => {
    setError('');
    const previous = documents;
    setDocuments((docs) => docs.filter((d) => d.id !== doc.id));
    const response = await fetch(`/api/documents/${doc.id}`, { method: 'DELETE' }).catch(() => null);
    if (!response || !response.ok) {
      setDocuments(previous);
      setError(`Could not remove “${doc.title}”.`);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="library-title"
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-3xl border border-slate-800 bg-[#0b1020] p-5 sm:p-6 text-left shadow-2xl outline-none"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="library-title" className="flex items-center gap-2 text-lg font-semibold text-white">
              <BookOpen className="h-5 w-5 text-cyan-400" /> Knowledge library
            </h2>
            <p className="mt-1 text-xs text-slate-400">
              Add lecture notes, textbook chapters or worksheets. The tutor looks things up here first and cites the page it used.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close library" className="rounded-full p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); uploadFiles(e.dataTransfer.files); }}
          className={`mt-5 rounded-2xl border-2 border-dashed p-6 text-center transition ${dragging ? 'border-cyan-400 bg-cyan-950/30' : 'border-slate-700 bg-slate-950/40'}`}
        >
          <UploadCloud className="mx-auto h-8 w-8 text-cyan-400" />
          <p className="mt-2 text-sm text-slate-200">Drop PDF or text files here</p>
          <p className="mt-1 text-[11px] text-slate-500">PDF, TXT or Markdown · up to {meta.max_upload_mb || 20} MB each</p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            <button type="button" onClick={() => inputRef.current?.click()} className="rounded-xl bg-cyan-600 px-4 py-2 text-xs font-semibold text-white hover:bg-cyan-500">
              Choose files
            </button>
            <button type="button" onClick={() => setPasteOpen((v) => !v)} className="flex items-center gap-1.5 rounded-xl border border-slate-700 px-4 py-2 text-xs text-slate-300 hover:text-white">
              <ClipboardPaste className="h-3.5 w-3.5" /> Paste text
            </button>
          </div>
          <input ref={inputRef} type="file" accept={ACCEPT} multiple className="hidden" data-testid="library-file-input" onChange={(e) => uploadFiles(e.target.files)} />
        </div>

        {pasteOpen && (
          <form onSubmit={submitPaste} className="mt-4 space-y-2">
            <input value={pasteTitle} onChange={(e) => setPasteTitle(e.target.value)} placeholder="Title (e.g. Chapter 4 notes)" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500" />
            <textarea value={pasteText} onChange={(e) => setPasteText(e.target.value)} rows={5} placeholder="Paste notes or an explanation…" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500" />
            <div className="flex justify-end">
              <button disabled={pasteBusy || !pasteText.trim()} className="rounded-xl bg-cyan-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-40">
                {pasteBusy ? 'Saving…' : 'Add to library'}
              </button>
            </div>
          </form>
        )}

        {queue.length > 0 && (
          <ul className="mt-4 space-y-1.5" aria-live="polite">
            {queue.map((item) => (
              <li key={item.name} className="flex items-center gap-2 text-xs">
                {item.status === 'uploading' && <Loader2 className="h-4 w-4 animate-spin text-cyan-400" />}
                {item.status === 'done' && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
                {item.status === 'error' && <AlertTriangle className="h-4 w-4 text-rose-400" />}
                <span className="truncate text-slate-200">{item.name}</span>
                <span className={item.status === 'error' ? 'text-rose-300' : 'text-slate-500'}>{item.status === 'uploading' ? 'Reading and indexing…' : item.message}</span>
              </li>
            ))}
          </ul>
        )}

        {error && <p className="mt-3 rounded-xl border border-rose-800/60 bg-rose-950/20 px-3 py-2 text-xs text-rose-200">{error}</p>}

        <div className="mt-5">
          <h3 className="text-xs font-mono uppercase tracking-wider text-slate-500">In your library ({documents.length})</h3>
          {loading && !documents.length ? (
            <p className="mt-3 text-xs text-slate-500">Loading…</p>
          ) : !documents.length ? (
            <p className="mt-3 text-xs text-slate-500">Nothing here yet. Files you add are used to support the tutor’s explanations, quizzes and study plans.</p>
          ) : (
            <ul className="mt-2 divide-y divide-slate-800" data-testid="library-list">
              {documents.map((doc) => (
                <li key={doc.id} className="flex items-center gap-3 py-2.5">
                  <FileText className="h-5 w-5 shrink-0 text-slate-400" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-slate-100">{doc.title}</p>
                    <p className="text-[11px] text-slate-500">
                      {doc.pages} page{doc.pages === 1 ? '' : 's'} · {doc.chunk_count} passages · {formatWhen(doc.created_at)}
                      {' · '}
                      <span className={doc.embedded ? 'text-emerald-400' : 'text-amber-300'} title={doc.embedded ? 'Keyword and meaning-based search' : 'Keyword search now; meaning-based search when an embedding model is available (ollama pull nomic-embed-text)'}>
                        {doc.embedded ? 'semantic search ready' : 'keyword search'}
                      </span>
                    </p>
                  </div>
                  <button type="button" onClick={() => remove(doc)} aria-label={`Remove ${doc.title}`} className="rounded-lg p-1.5 text-slate-500 hover:bg-rose-950/40 hover:text-rose-300">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
};
