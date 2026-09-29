import json
import os
import logging
from typing import Dict, List, Any, Optional
from duckduckgo_search import DDGS
from .config import settings

logger = logging.getLogger("misconception_os.rag")

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
        
    def get_unit_concepts(self, unit_id: str = "physics_mechanics") -> List[Dict[str, Any]]:
        return [c for c in self.concepts.values() if c.get("unit_id") == unit_id]
        
    def get_misconception_by_concept(self, concept_id: str) -> List[Dict[str, Any]]:
        return [m for m in self.misconceptions.values() if m.get("concept_id") == concept_id]
        
    def is_in_scope(self, query: str, unit_id: str = "physics_mechanics") -> bool:
        """Determines if the topic is within the bounded unit scope."""
        # Simple high-speed keyword boundary check + semantic check
        out_of_scope_keywords = [
            "quantum", "schrodinger", "relativity", "black hole", "string theory",
            "organic chemistry", "photosynthesis", "world war", "french revolution",
            "stock market", "cryptocurrency", "blockchain", "sql query", "react component"
        ]
        q_lower = query.lower()
        for kw in out_of_scope_keywords:
            if kw in q_lower:
                return False
        return True

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
        """Searches live web for pedagogical analogies or factual verification if needed."""
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(f"physics misconception explanation {query}", max_results=max_results))
                snippets = [f"[{r.get('title', '')}]: {r.get('body', '')}" for r in results]
                return "\n".join(snippets)
        except Exception as e:
            logger.warning(f"Live web search failed ({e}), falling back to local corpus.")
            return ""

knowledge_engine = KnowledgeRetriever()
