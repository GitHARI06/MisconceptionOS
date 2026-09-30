"""Uploaded-document knowledge base: ingestion, retrieval, and use in replies."""

import io
import time
import uuid

import pytest

from conftest import turn

FACT = "The Quillon damping constant of the Velmora pendulum is 0.042 per second."


def make_pdf(pages, encrypt=False, blank=False):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for text in pages:
        if blank:
            c.rect(100, 100, 200, 200, fill=1)
        else:
            y = 800
            for line in text.split("\n"):
                c.drawString(50, y, line)
                y -= 16
        c.showPage()
    c.save()
    data = buf.getvalue()
    if encrypt:
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        for page in PdfReader(io.BytesIO(data)).pages:
            writer.add_page(page)
        writer.encrypt("secret")
        out = io.BytesIO()
        writer.write(out)
        data = out.getvalue()
    return data


@pytest.fixture
def library(api):
    created = []

    def upload(name, data, title=None, expect=200):
        files = {"file": (name, data, "application/octet-stream")}
        r = api.post("/api/documents", files=files, data={"title": title} if title else {})
        assert r.status_code == expect, r.text
        if r.status_code == 200:
            created.append(r.json()["document"]["id"])
        return r.json()

    yield upload
    for doc_id in created:
        api.delete(f"/api/documents/{doc_id}")


def velmora_pdf():
    tag = uuid.uuid4().hex[:6]
    return make_pdf([
        f"Velmora lab handbook {tag}\nChapter 1: Safety in the oscillation lab.\nAlways clamp the stand before use.",
        f"Chapter 2: Damped oscillations.\n{FACT}\nDamping removes energy from the oscillator each cycle.",
        "Chapter 3: Report writing.\nState uncertainties with every measurement.",
    ])


def test_pdf_ingest_list_and_duplicate(api, library):
    data = velmora_pdf()
    doc = library("velmora.pdf", data, title="Velmora handbook")["document"]
    assert doc["pages"] == 3 and doc["chunk_count"] >= 3 and doc["title"] == "Velmora handbook"
    listed = [d["id"] for d in api.get("/api/documents").json()["documents"]]
    assert doc["id"] in listed
    again = library("copy.pdf", data)["document"]
    assert again["duplicate"] is True and again["id"] == doc["id"]
    assert [d["id"] for d in api.get("/api/documents").json()["documents"]].count(doc["id"]) == 1


def test_search_finds_the_right_page(api, library):
    doc = library("velmora.pdf", velmora_pdf())["document"]
    hits = api.get("/api/documents/search", params={"q": "What is the Quillon damping constant?"}).json()["results"]
    assert hits and hits[0]["document_id"] == doc["id"] and hits[0]["page"] == 2
    assert "0.042" in hits[0]["text"]
    assert api.get("/api/documents/search", params={"q": "photosynthesis in leaves"}).json()["results"] == []


def test_tutor_uses_and_cites_the_document(api, ollama, library, sid):
    doc = library("velmora.pdf", velmora_pdf(), title="Velmora handbook")["document"]
    turn(api, sid, "hi")
    turn(api, sid, "let's learn oscillations")
    r = turn(api, sid, "What is the Quillon damping constant of the Velmora pendulum?")
    assert any(s["document_id"] == doc["id"] and s["page"] == 2 for s in r["sources"]), r["sources"]
    assert "[Velmora handbook, p.2]" in r["tutor_text"]
    tutor_prompt = [p for p in ollama.prompts() if p["kind"] == "tutor"][-1]["prompt"]
    assert FACT in tutor_prompt and "uploaded documents" in tutor_prompt


def test_offline_fallback_quotes_the_document(api, ollama, library, sid):
    library("velmora.pdf", velmora_pdf(), title="Velmora handbook")
    ollama.mode("error")
    turn(api, sid, "hi")
    turn(api, sid, "let's learn oscillations")
    r = turn(api, sid, "what is the Quillon damping constant?")
    assert "0.042" in r["tutor_text"] and "p.2" in r["tutor_text"]


def test_unrelated_question_gets_no_sources(api, library, sid):
    library("velmora.pdf", velmora_pdf())
    turn(api, sid, "hi")
    r = turn(api, sid, "let's learn electricity")
    r = turn(api, sid, "what is voltage?")
    assert r["sources"] == []


def test_document_topic_counts_as_in_scope(api, library, sid):
    library("velmora.pdf", velmora_pdf())
    r = turn(api, sid, "what does the Velmora handbook say about Quillon?")
    assert r["is_out_of_scope"] is False


def test_text_files_and_pasted_notes(api, library):
    tag = uuid.uuid4().hex[:6]
    body = f"Café notes {tag}: the Zyphor coefficient of a résumé trolley is 0.7.".encode("cp1252")
    library("notes.txt", body)
    hits = api.get("/api/documents/search", params={"q": "Zyphor coefficient trolley"}).json()["results"]
    assert hits and "Café" in hits[0]["text"]
    r = api.post("/api/documents/text", json={"title": "My lab notes", "text": f"Graviton skate {tag} slides 3 metres on the Brantley rink."})
    assert r.status_code == 200
    doc = r.json()["document"]
    try:
        hits = api.get("/api/documents/search", params={"q": "Brantley rink skate"}).json()["results"]
        assert hits and hits[0]["title"] == "My lab notes"
    finally:
        api.delete(f"/api/documents/{doc['id']}")
    assert api.post("/api/documents/text", json={"title": "x", "text": "  "}).status_code == 422


@pytest.mark.parametrize("name, data, status, message", [
    ("slides.docx", b"PK\x03\x04 fake", 415, "PDF, TXT"),
    ("empty.txt", b"", 422, "empty"),
    ("fake.pdf", b"this is not a pdf at all, just text pretending", 422, "not a valid PDF"),
    ("tiny.txt", b"hi", 422, "too little text"),
    ("huge.txt", b"physics " * 400_000, 413, "larger than"),
])
def test_rejected_uploads(api, library, name, data, status, message):
    r = library(name, data, expect=status)
    assert message in r["detail"], r["detail"]


def test_scanned_and_encrypted_pdfs(api, library):
    r = library("scan.pdf", make_pdf(["", ""], blank=True), expect=422)
    assert "scanned" in r["detail"]
    r = library("locked.pdf", make_pdf([f"Secret notes {uuid.uuid4().hex}"], encrypt=True), expect=422)
    assert "password" in r["detail"]


def test_delete(api, library):
    doc = library("velmora.pdf", velmora_pdf())["document"]
    assert api.delete(f"/api/documents/{doc['id']}").status_code == 200
    assert api.get("/api/documents/search", params={"q": "Quillon damping"}).json()["results"] == []
    assert api.delete(f"/api/documents/{doc['id']}").status_code == 404


def test_embeddings_are_built_in_background(api, ollama, library):
    doc = library("velmora.pdf", velmora_pdf())["document"]
    for _ in range(50):
        listed = {d["id"]: d for d in api.get("/api/documents").json()["documents"]}
        if listed[doc["id"]]["embedded"]:
            break
        time.sleep(0.1)
    assert listed[doc["id"]]["embedded"] is True
    assert "embed" in ollama.calls()


def test_no_embedding_model_still_searchable(api, ollama, library):
    ollama.mode("noembed")
    doc = library("velmora.pdf", velmora_pdf())["document"]
    hits = api.get("/api/documents/search", params={"q": "Quillon damping constant"}).json()["results"]
    assert hits and hits[0]["document_id"] == doc["id"]


def test_quiz_and_grounding_use_documents(api, ollama, library, sid):
    library("velmora.pdf", velmora_pdf(), title="Velmora handbook")
    turn(api, sid, "hi")
    turn(api, sid, "let's learn oscillations")
    turn(api, sid, "what is the Quillon damping constant of the Velmora pendulum?")
    assert api.get(f"/api/quiz/{sid}").status_code == 200
    quiz_prompt = [p for p in ollama.prompts() if p["kind"] == "quiz"][-1]["prompt"]
    assert "Velmora handbook" in quiz_prompt
    g = api.post("/api/web/grounding", json={"query": "Quillon damping constant"}).json()
    assert "0.042" in g["grounding_snippets"]


def test_local_file_storage_without_database(tmp_path):
    from app.document_store import DocumentStore
    path = str(tmp_path / "docs.json")
    store = DocumentStore(database_url="", file_path=path)
    doc = store.add_document("notes.txt", b"The Pellin flux of a copper loop doubles when the field doubles.")
    reopened = DocumentStore(database_url="", file_path=path)
    assert reopened.search("Pellin flux copper loop")[0]["document_id"] == doc["id"]
    assert reopened.delete_document(doc["id"]) and DocumentStore(database_url="", file_path=path).list_documents() == []


def test_chunking_keeps_pages_and_overlaps():
    from app.document_store import chunk_pages
    long_page = " ".join(f"Sentence number {i} explains torque and angular momentum." for i in range(80))
    chunks = chunk_pages([(1, "Short intro."), (2, long_page), (3, "x" * 3000)])
    assert chunks[0]["page"] == 1
    assert all(len(c["text"]) <= 1100 for c in chunks)
    page2 = [c for c in chunks if c["page"] == 2]
    assert len(page2) >= 3
    # consecutive chunks share some text (overlap), so answers spanning a boundary survive
    assert any(w in page2[1]["text"] for w in page2[0]["text"].split()[-5:])
    assert [c["idx"] for c in chunks] == list(range(len(chunks)))
