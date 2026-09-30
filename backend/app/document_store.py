"""Uploaded-document knowledge base (RAG).

Pipeline
  upload (.pdf / .txt / .md or pasted text)
    -> text extraction (pypdf, page by page; robust text decoding)
    -> cleaning (de-hyphenation, whitespace)
    -> sentence-aware chunking (~900 chars, 150 overlap, page numbers kept)
    -> storage in PostgreSQL (or a local JSON file when no database is set)
    -> indexing: BM25 keyword index (always) + Ollama embeddings (when an
       embedding model is available), fused with reciprocal-rank fusion.

Retrieval is in memory and takes milliseconds, so it can run on every tutor
turn. Embeddings are computed in a background thread after upload, so a large
PDF is searchable by keyword immediately and semantically a little later.
"""

import hashlib
import io
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import requests

from .config import settings

logger = logging.getLogger("misconception_os.documents")

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown", ".text"}
CHUNK_CHARS = 900
CHUNK_OVERLAP = 150
MIN_DOCUMENT_CHARS = 40

_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "were", "be",
    "it", "its", "this", "that", "these", "those", "with", "as", "by", "at", "from", "if", "then",
    "so", "do", "does", "did", "what", "why", "how", "which", "who", "when", "where", "can", "could",
    "would", "should", "i", "you", "we", "they", "he", "she", "me", "my", "your", "our", "their",
    "not", "no", "yes", "but", "about", "into", "than", "there", "here", "also", "will", "just",
    "please", "tell", "explain", "let", "lets", "us", "some", "any", "has", "have", "had",
}


class DocumentError(ValueError):
    """A problem with an uploaded document that the user can fix."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def tokenize(text: str) -> List[str]:
    tokens = []
    for token in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if token in _STOP or len(token) < 2:
            continue
        # light stemming: forces -> force, accelerating -> accelerat
        for suffix in ("ations", "ation", "ing", "ies", "es", "s"):
            if len(token) > len(suffix) + 3 and token.endswith(suffix):
                token = token[: -len(suffix)] + ("y" if suffix == "ies" else "")
                break
        tokens.append(token)
    return tokens


# --------------------------------------------------------------------------
# Extraction and chunking
# --------------------------------------------------------------------------

def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(encoding)
            if encoding == "utf-16" and not data[:2] in (b"\xff\xfe", b"\xfe\xff"):
                raise UnicodeDecodeError(encoding, data, 0, 1, "no BOM")
            return text
        except UnicodeDecodeError:
            continue
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _clean(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # re-join hyphenated line breaks
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(filename: str, data: bytes) -> List[Tuple[int, str]]:
    """Return [(page_number, text)]. Plain-text files are a single page."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentError("Only PDF, TXT and Markdown files can be added.", 415)
    if not data:
        raise DocumentError("The file is empty.")
    if ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise DocumentError("This file is not a valid PDF.")
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise DocumentError("PDF support needs the pypdf package (pip install pypdf).", 503) from exc
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                try:
                    if not reader.decrypt(""):
                        raise DocumentError("This PDF is password-protected. Remove the password and upload it again.")
                except DocumentError:
                    raise
                except Exception as exc:
                    raise DocumentError("This PDF is password-protected. Remove the password and upload it again.") from exc
            pages = []
            for number, page in enumerate(reader.pages, start=1):
                try:
                    pages.append((number, _clean(page.extract_text() or "")))
                except Exception as exc:  # one broken page must not sink the file
                    logger.warning("Could not read page %s of %s: %s", number, filename, exc)
            return pages
        except DocumentError:
            raise
        except Exception as exc:
            raise DocumentError(f"The PDF could not be read ({exc.__class__.__name__}). It may be damaged.") from exc
    return [(1, _clean(_decode_text(data)))]


def chunk_pages(pages: List[Tuple[int, str]]) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    for page_number, text in pages:
        if not text.strip():
            continue
        sentences = re.split(r"(?<=[.!?])\s+|\n{2,}", text)
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            # A single enormous "sentence" (tables, no punctuation) is hard-split.
            while len(sentence) > CHUNK_CHARS:
                head, sentence = sentence[:CHUNK_CHARS], sentence[CHUNK_CHARS - CHUNK_OVERLAP:]
                if current:
                    chunks.append({"page": page_number, "text": current.strip()})
                    current = ""
                chunks.append({"page": page_number, "text": head.strip()})
            if len(current) + len(sentence) + 1 > CHUNK_CHARS and current:
                chunks.append({"page": page_number, "text": current.strip()})
                current = current[-CHUNK_OVERLAP:].split(" ", 1)[-1] + " " + sentence
            else:
                current = f"{current} {sentence}" if current else sentence
        if current.strip():
            chunks.append({"page": page_number, "text": current.strip()})
    for index, chunk in enumerate(chunks):
        chunk["idx"] = index
    return chunks


# --------------------------------------------------------------------------
# Embeddings (optional, via Ollama)
# --------------------------------------------------------------------------

_embed_failed_at = 0.0


def embed_texts(texts: List[str], timeout: float = 30.0, respect_backoff: bool = False) -> Optional[List[List[float]]]:
    """Embed with Ollama. Returns None when no embedding model is available.

    respect_backoff=True is used for live questions: after a failure they skip
    embeddings for a minute so no learner waits on a missing model. Indexing
    uploaded documents always tries (and is retried later if it fails)."""
    global _embed_failed_at
    if not settings.ENABLE_EMBEDDINGS or not texts:
        return None
    if respect_backoff and time.time() - _embed_failed_at < 60:
        return None
    try:
        response = requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/embed",
            json={"model": settings.EMBED_MODEL, "input": texts},
            timeout=timeout,
        )
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:120]}")
        vectors = response.json().get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise RuntimeError("unexpected embedding response")
        return [[float(x) for x in vector] for vector in vectors]
    except Exception as exc:
        _embed_failed_at = time.time()
        logger.info("Embeddings unavailable (%s); using keyword retrieval only. "
                    "Run `ollama pull %s` for semantic search.", exc, settings.EMBED_MODEL)
        return None


def _normalize(vector: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------

class DocumentStore:
    def __init__(self, database_url: Optional[str] = None, file_path: Optional[str] = None):
        self.database_url = database_url if database_url is not None else settings.DATABASE_URL
        self.file_path = file_path or settings.DOCUMENT_STORE_PATH
        self._psycopg = None
        self._dict_row = None
        self._lock = threading.RLock()
        self.documents: Dict[str, Dict[str, Any]] = {}
        self.chunks: List[Dict[str, Any]] = []
        self._rebuild_index()
        if self.database_url:
            try:
                import psycopg
                from psycopg.rows import dict_row
                self._psycopg, self._dict_row = psycopg, dict_row
                self._ensure_schema()
            except Exception as exc:
                logger.warning("Document storage falls back to a local file (%s).", exc)
                self._psycopg = None
        self._last_embed_retry = 0.0
        self._load()

    # ---- persistence ---------------------------------------------------
    @property
    def uses_database(self) -> bool:
        return bool(self._psycopg)

    def _connect(self):
        return self._psycopg.connect(self.database_url, row_factory=self._dict_row)

    def _ensure_schema(self):
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rag_documents (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        sha256 TEXT NOT NULL UNIQUE,
                        pages INTEGER NOT NULL,
                        chars INTEGER NOT NULL,
                        chunk_count INTEGER NOT NULL,
                        embedded BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rag_chunks (
                        id BIGSERIAL PRIMARY KEY,
                        document_id TEXT NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
                        idx INTEGER NOT NULL,
                        page INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        embedding REAL[]
                    )
                    """
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc ON rag_chunks (document_id, idx)")

    def _load(self):
        with self._lock:
            documents, chunks = {}, []
            try:
                if self.uses_database:
                    with self._connect() as connection:
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT * FROM rag_documents ORDER BY created_at")
                            for row in cursor.fetchall():
                                row["created_at"] = row["created_at"].isoformat()
                                documents[row["id"]] = dict(row)
                            cursor.execute("SELECT document_id, idx, page, text, embedding FROM rag_chunks ORDER BY document_id, idx")
                            chunks = [dict(row) for row in cursor.fetchall()]
                elif os.path.exists(self.file_path):
                    with open(self.file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    documents, chunks = data.get("documents", {}), data.get("chunks", [])
            except Exception as exc:
                logger.error("Could not load uploaded documents: %s", exc)
            self.documents, self.chunks = documents, chunks
            self._rebuild_index()

    def _save_file(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        tmp = self.file_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"documents": self.documents, "chunks": self.chunks}, f)
        os.replace(tmp, self.file_path)

    # ---- index -----------------------------------------------------------
    def _rebuild_index(self):
        self._tokens = [tokenize(c["text"]) for c in self.chunks]
        self._tf = [Counter(tokens) for tokens in self._tokens]
        self._lengths = [len(tokens) for tokens in self._tokens]
        self._avg_len = (sum(self._lengths) / len(self._lengths)) if self._lengths else 1.0
        df: Counter = Counter()
        for tokens in self._tokens:
            df.update(set(tokens))
        n = len(self.chunks)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self._vectors = [
            _normalize(c["embedding"]) if c.get("embedding") else None for c in self.chunks
        ]

    def _bm25(self, query_tokens: List[str]) -> List[Tuple[float, int]]:
        k1, b = 1.4, 0.75
        scores = []
        for i, tf in enumerate(self._tf):
            score = 0.0
            for token in query_tokens:
                if token not in tf:
                    continue
                freq = tf[token]
                idf = self._idf.get(token, 0.0)
                score += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * self._lengths[i] / self._avg_len))
            if score > 0:
                scores.append((score, i))
        scores.sort(reverse=True)
        return scores

    # ---- public API --------------------------------------------------------
    def list_documents(self) -> List[Dict[str, Any]]:
        with self._lock:
            return sorted(
                (dict(doc) for doc in self.documents.values()),
                key=lambda d: d.get("created_at", ""), reverse=True,
            )

    def add_document(self, filename: str, data: bytes, title: Optional[str] = None) -> Dict[str, Any]:
        max_bytes = int(settings.MAX_UPLOAD_MB * 1024 * 1024)
        if len(data) > max_bytes:
            raise DocumentError(f"The file is larger than {settings.MAX_UPLOAD_MB:g} MB.", 413)
        sha = hashlib.sha256(data).hexdigest()
        with self._lock:
            for doc in self.documents.values():
                if doc["sha256"] == sha:
                    return {**doc, "duplicate": True}

        pages = extract_pages(filename, data)
        total_chars = sum(len(text) for _, text in pages)
        if total_chars < MIN_DOCUMENT_CHARS:
            if filename.lower().endswith(".pdf"):
                raise DocumentError(
                    "No readable text was found in this PDF. It is probably a scanned image; "
                    "export it with text (or run OCR) and upload it again."
                )
            raise DocumentError("The document has too little text to be useful.")
        chunks = chunk_pages(pages)
        doc_id = uuid.uuid4().hex[:16]
        clean_title = (title or os.path.splitext(os.path.basename(filename))[0] or "Document").strip()[:120]
        doc = {
            "id": doc_id,
            "title": clean_title,
            "filename": os.path.basename(filename)[:200],
            "sha256": sha,
            "pages": max((p for p, _ in pages), default=1),
            "chars": total_chars,
            "chunk_count": len(chunks),
            "embedded": False,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        rows = [{"document_id": doc_id, "idx": c["idx"], "page": c["page"], "text": c["text"], "embedding": None} for c in chunks]

        with self._lock:
            if self.uses_database:
                with self._connect() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "INSERT INTO rag_documents (id, title, filename, sha256, pages, chars, chunk_count) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING created_at",
                            (doc_id, doc["title"], doc["filename"], sha, doc["pages"], total_chars, len(chunks)),
                        )
                        doc["created_at"] = cursor.fetchone()["created_at"].isoformat()
                        cursor.executemany(
                            "INSERT INTO rag_chunks (document_id, idx, page, text) VALUES (%s, %s, %s, %s)",
                            [(doc_id, r["idx"], r["page"], r["text"]) for r in rows],
                        )
            self.documents[doc_id] = doc
            self.chunks.extend(rows)
            if not self.uses_database:
                self._save_file()
            self._rebuild_index()

        threading.Thread(target=self._embed_document, args=(doc_id,), daemon=True).start()
        return dict(doc)

    def _embed_document(self, doc_id: str):
        with self._lock:
            targets = [c for c in self.chunks if c["document_id"] == doc_id and not c.get("embedding")]
        vectors: List[List[float]] = []
        for start in range(0, len(targets), 32):
            batch = embed_texts([c["text"] for c in targets[start:start + 32]], timeout=60.0)
            if batch is None:
                return
            vectors.extend(batch)
        with self._lock:
            if doc_id not in self.documents:
                return  # deleted while embedding
            for chunk, vector in zip(targets, vectors):
                chunk["embedding"] = vector
            self.documents[doc_id]["embedded"] = True
            try:
                if self.uses_database:
                    with self._connect() as connection:
                        with connection.cursor() as cursor:
                            cursor.executemany(
                                "UPDATE rag_chunks SET embedding = %s WHERE document_id = %s AND idx = %s",
                                [(c["embedding"], doc_id, c["idx"]) for c in targets],
                            )
                            cursor.execute("UPDATE rag_documents SET embedded = TRUE WHERE id = %s", (doc_id,))
                else:
                    self._save_file()
            except Exception as exc:
                logger.warning("Could not store embeddings for %s: %s", doc_id, exc)
            self._rebuild_index()

    def _maybe_retry_embeddings(self):
        """Documents uploaded while no embedding model was reachable get
        another chance (at most every two minutes), in the background."""
        now = time.time()
        if not settings.ENABLE_EMBEDDINGS or now - getattr(self, "_last_embed_retry", 0) < 120:
            return
        with self._lock:
            pending = [doc_id for doc_id, doc in self.documents.items() if not doc.get("embedded")]
        if not pending:
            return
        self._last_embed_retry = now

        def run():
            for doc_id in pending:
                self._embed_document(doc_id)

        threading.Thread(target=run, daemon=True).start()

    def delete_document(self, doc_id: str) -> bool:
        with self._lock:
            if doc_id not in self.documents:
                return False
            if self.uses_database:
                with self._connect() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("DELETE FROM rag_documents WHERE id = %s", (doc_id,))
            del self.documents[doc_id]
            self.chunks = [c for c in self.chunks if c["document_id"] != doc_id]
            if not self.uses_database:
                self._save_file()
            self._rebuild_index()
            return True

    def search(self, query: str, k: Optional[int] = None, use_embeddings: bool = True) -> List[Dict[str, Any]]:
        """Hybrid retrieval. Returns the best chunks with their source, or []
        when nothing is genuinely relevant (so unrelated notes are never
        stuffed into the tutor's prompt)."""
        k = k or settings.RAG_TOP_K
        query = (query or "").strip()
        self._maybe_retry_embeddings()
        with self._lock:
            if not query or not self.chunks:
                return []
            query_tokens = tokenize(query)
            bm25 = self._bm25(query_tokens) if query_tokens else []
            ranked: Dict[int, float] = {}
            best_bm25 = bm25[0][0] if bm25 else 0.0
            # Keyword hits must cover a meaningful part of the query.
            for rank, (score, i) in enumerate(bm25[:50]):
                matched = len(set(query_tokens) & set(self._tf[i]))
                if matched >= max(1, math.ceil(len(set(query_tokens)) * 0.3)) and score >= 0.35 * best_bm25:
                    ranked[i] = ranked.get(i, 0.0) + 1.0 / (60 + rank)
            vectors_available = any(v is not None for v in self._vectors)

        if use_embeddings and vectors_available:
            query_vector = embed_texts([query], timeout=2.0, respect_backoff=True)
            if query_vector:
                qv = _normalize(query_vector[0])
                with self._lock:
                    sims = [
                        (sum(a * b for a, b in zip(qv, v)), i)
                        for i, v in enumerate(self._vectors) if v is not None and len(v) == len(qv)
                    ]
                    sims.sort(reverse=True)
                    for rank, (sim, i) in enumerate(sims[:50]):
                        if sim >= 0.55:
                            ranked[i] = ranked.get(i, 0.0) + 1.0 / (60 + rank)

        with self._lock:
            ordered = sorted(ranked.items(), key=lambda item: item[1], reverse=True)
            results, seen = [], set()
            for i, score in ordered:
                if i >= len(self.chunks):
                    continue
                chunk = self.chunks[i]
                key = (chunk["document_id"], chunk["idx"])
                if key in seen or chunk["document_id"] not in self.documents:
                    continue
                seen.add(key)
                doc = self.documents[chunk["document_id"]]
                results.append({
                    "document_id": chunk["document_id"],
                    "title": doc["title"],
                    "filename": doc["filename"],
                    "page": chunk["page"],
                    "text": chunk["text"],
                    "score": round(score, 5),
                })
                if len(results) >= k:
                    break
            return results


def format_references(hits: List[Dict[str, Any]], max_chars: int = 3500) -> str:
    """Render retrieved chunks for an LLM prompt, each tagged with its source."""
    blocks, used = [], 0
    for hit in hits:
        label = f"[{hit['title']}, p.{hit['page']}]"
        text = hit["text"]
        if used + len(text) > max_chars:
            text = text[: max(0, max_chars - used)]
        if not text:
            break
        blocks.append(f"{label} {text}")
        used += len(text)
    return "\n\n".join(blocks)


def source_list(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compact, de-duplicated citations for the UI."""
    sources, seen = [], set()
    for hit in hits:
        key = (hit["document_id"], hit["page"])
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "document_id": hit["document_id"],
            "title": hit["title"],
            "page": hit["page"],
            "snippet": hit["text"][:220] + ("…" if len(hit["text"]) > 220 else ""),
        })
    return sources


document_store = DocumentStore()
