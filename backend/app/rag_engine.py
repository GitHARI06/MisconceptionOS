import json
import os
import logging
import re
from typing import Dict, List, Any, Optional
from .config import settings

logger = logging.getLogger("misconception_os.rag")

# Everyday words that must never count as evidence that a query is about
# physics when it is matched against the local corpus.
STOPWORDS = {
    "what", "are", "the", "and", "for", "why", "how", "with", "about", "this", "that", "from",
    "into", "your", "you", "tell", "help", "please", "can", "does", "did", "who", "when", "where",
    "which", "will", "would", "should", "could", "have", "has", "had", "was", "were", "been",
    "its", "they", "them", "their", "there", "then", "than", "some", "any", "our", "out", "not",
    "but", "all", "one", "two", "use", "used", "using", "make", "like", "just", "more", "most",
    "explain", "give", "show", "write", "need", "want", "know", "learn", "teach", "study",
}

class KnowledgeRetriever:
    def __init__(self, data_path: Optional[str] = None):
        if data_path is None:
            data_path = os.path.join(settings.DATA_DIR, "knowledge_base.json")
        self.data_path = data_path
        self.units: Dict[str, Any] = {}
        self.concepts: Dict[str, Any] = {}
        self.challenges: Dict[str, Any] = {}
        self.misconceptions: Dict[str, Any] = {}
        self.load_data()
        
    def load_data(self):
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for unit in data.get("units", []):
                    u_id = unit["id"]
                    self.units[u_id] = unit
                    for c in unit.get("concepts", []):
                        self.concepts[c["id"]] = {**c, "unit_id": u_id}
                    for m in unit.get("misconception_library", []):
                        self.misconceptions[m["id"]] = {**m, "unit_id": u_id}
                    for ch in unit.get("diagnostic_challenges", []):
                        self.challenges[ch["id"]] = {**ch, "unit_id": u_id}
            logger.info(f"Loaded {len(self.concepts)} concepts, {len(self.misconceptions)} misconceptions, {len(self.challenges)} challenges.")
        except Exception as e:
            logger.error(f"Failed to load knowledge base: {e}")
            
    def get_concept(self, concept_id: str) -> Optional[Dict[str, Any]]:
        return self.concepts.get(concept_id)
        
    def get_challenge(self, challenge_id: str) -> Optional[Dict[str, Any]]:
        return self.challenges.get(challenge_id)
        
    # Keywords that identify a curriculum challenge when the tutor presents
    # it in free-form conversation (the UI always sends "freeform_inquiry").
    CHALLENGE_SIGNATURES = {
        "CHALLENGE_01_INERTIA": [("puck",), ("frictionless", "ice")],
        "CHALLENGE_02_FREEFALL": [("bowling",), ("vacuum", "ball"), ("vacuum", "feather")],
        "CHALLENGE_03_PEAK_ACCEL": [("pendulum", "highest"), ("pendulum", "turning point")],
    }

    def infer_challenge(self, text: str) -> Optional[Dict[str, Any]]:
        text = (text or "").lower()
        for challenge_id, signatures in self.CHALLENGE_SIGNATURES.items():
            if any(all(word in text for word in signature) for signature in signatures):
                return self.get_challenge(challenge_id)
        return None

    def get_unit_concepts(self, unit_id: str = "physics_mechanics") -> List[Dict[str, Any]]:
        return [c for c in self.concepts.values() if c.get("unit_id") == unit_id]
        
    def get_misconception_by_concept(self, concept_id: str) -> List[Dict[str, Any]]:
        return [m for m in self.misconceptions.values() if m.get("concept_id") == concept_id]
        
    def is_in_scope(self, query: str, unit_id: str = "physics_mechanics") -> bool:
        """Determine whether a query has a physics framing."""
        # Imported lazily to avoid a module cycle during knowledge-base boot.
        from .safety_guard import SafetyGuardrail
        return SafetyGuardrail.is_physics_query(query)

    def retrieve_grounded_context(self, concept_id: str) -> str:
        """Constructs grounded reference context from local approved corpus."""
        concept = self.get_concept(concept_id)
        if not concept:
            return ""
        
        prereqs = [self.get_concept(p)["name"] for p in concept.get("prerequisites", []) if self.get_concept(p)]
        prereq_str = ", ".join(prereqs) if prereqs else "None (Foundational)"
        
        misconceptions = self.get_misconception_by_concept(concept_id)
        misc_str = "\n".join([f"- Misconception: {m['name']} ({m['category']})\n  Description: {m['description']}\n  Counter-Example: {m['counter_example']}" for m in misconceptions])
        
        context = f"""
Approved Knowledge Boundary:
Concept: {concept['name']}
Definition: {concept['definition']}
Prerequisites: {prereq_str}
Key Formulas: {', '.join(concept.get('key_formulas', []))}

Known Student Misconceptions & Pedagogical Counter-Examples:
{misc_str}
"""
        return context.strip()

    def search_live_grounding(self, query: str, max_results: int = 2) -> str:
        """Search live web, then fall back to the approved local physics corpus."""
        query = (query or "").strip()
        if not query:
            return "Enter a physics concept or question to retrieve grounding."

        if not settings.ENABLE_WEB_SEARCH:
            return self._local_grounding(query)

        try:
            from duckduckgo_search import DDGS
            with DDGS(timeout=settings.WEB_SEARCH_TIMEOUT_SECONDS) as ddgs:
                results = list(ddgs.text(f"physics misconception explanation {query}", max_results=max_results))
                snippets = [f"[{r.get('title', '')}]: {r.get('body', '')}" for r in results]
                if snippets:
                    return "\n\n".join(snippets)
        except Exception as e:
            logger.warning(f"Live web search failed ({e}), using local grounding.")

        return self._local_grounding(query)

    def _local_grounding(self, query: str) -> str:
        """Return relevant, inspectable snippets when live retrieval is empty."""
        terms = {
            token.rstrip("s") for token in re.findall(r"[a-z0-9]+", query.lower())
            if len(token) > 2 and token not in STOPWORDS
        }
        candidates = []

        for unit in self.units.values():
            unit_text = re.sub(r"[^a-z0-9 ]", " ", " ".join(str(unit.get(k, "")) for k in ["name", "domain", "description"]).lower())
            unit_score = sum(term in unit_text for term in terms)
            if unit_score:
                candidates.append((unit_score, f"[Local approved corpus — {unit.get('name', 'Physics')}]: {unit.get('description', '')}"))

        for concept in self.concepts.values():
            concept_text = re.sub(r"[^a-z0-9 ]", " ", " ".join([
                str(concept.get("name", "")),
                str(concept.get("definition", "")),
                " ".join(concept.get("key_formulas", [])),
            ]).lower())
            score = sum(term in concept_text for term in terms)
            if score:
                candidates.append((score + 1, f"[Local concept — {concept.get('name', '')}]: {concept.get('definition', '')} Key formulas: {', '.join(concept.get('key_formulas', []))}"))

        for misconception in self.misconceptions.values():
            misc_text = re.sub(r"[^a-z0-9 ]", " ", " ".join([
                str(misconception.get("name", "")),
                str(misconception.get("description", "")),
                str(misconception.get("counter_example", "")),
            ]).lower())
            score = sum(term in misc_text for term in terms)
            if score:
                candidates.append((score, f"[Local misconception — {misconception.get('name', '')}]: {misconception.get('description', '')} Counter-example: {misconception.get('counter_example', '')}"))

        if not candidates:
            return (
                "Live search returned no results, and this concept is not yet in the local approved corpus. "
                "Use the tutor's physics explanation with caution until a source is available."
            )

        candidates.sort(key=lambda item: item[0], reverse=True)
        return "\n\n".join(snippet for _, snippet in candidates[:3])

knowledge_engine = KnowledgeRetriever()
