import React, { useState } from 'react';
import { Globe, Search, RefreshCw, BookOpen } from 'lucide-react';

export const WebGroundingViewer = () => {
  const [query, setQuery] = useState("Newton first law misconceptions voyager space probe");
  const [results, setResults] = useState("");
  const [loading, setLoading] = useState(false);

  const fetchGrounding = async () => {
    if (!query) return;
    setLoading(true);
    try {
      const res = await fetch('/api/web/grounding', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query })
      });
      if (res.ok) {
        const json = await res.json();
        setResults(json.grounding_snippets || "No search results returned.");
      }
    } catch (e) {
      console.error(e);
      setResults("Failed to retrieve live web grounding.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-5 bg-slate-900 border border-slate-800 rounded-2xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
            <Globe className="w-4 h-4 text-cyan-400" />
            Live Web Grounding & Fact-Checking Engine
          </h3>
          <p className="text-xs text-slate-400">
            Real-time web retrieval to ground counter-examples and eliminate hallucinations while maintaining Socratic boundaries.
          </p>
        </div>
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Enter concept or query for factual grounding..."
          className="flex-1 bg-slate-950 border border-slate-700 text-xs text-slate-200 rounded-xl px-4 py-2.5 focus:ring-1 focus:ring-teal-500 focus:outline-none font-mono"
        />
        <button
          onClick={fetchGrounding}
          disabled={loading}
          className="px-5 py-2.5 bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs rounded-xl flex items-center gap-1.5 transition"
        >
          {loading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
          Retrieve Grounding
        </button>
      </div>

      {results && (
        <div className="p-4 bg-slate-950 border border-slate-800 rounded-xl">
          <span className="text-[11px] font-mono text-cyan-400 block mb-2 font-semibold flex items-center gap-1.5">
            <BookOpen className="w-3.5 h-3.5" /> Retrieved Knowledge Snippets:
          </span>
          <pre className="text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed">
            {results}
          </pre>
        </div>
      )}
    </div>
  );
};
