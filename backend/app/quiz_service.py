"""Persistent concept quizzes, scoring, and adaptive study plans."""

import json
import logging
import requests
from typing import Any, Dict, List

from .config import settings
from .postgres_memory import concept_memory
from .rag_engine import knowledge_engine

logger = logging.getLogger("misconception_os.quiz")


class QuizService:
    def __init__(self):
        self.db = concept_memory

    def _connect(self):
        return self.db._connect()

    def ensure_schema(self):
        if not self.db.enabled:
            return
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS concept_quizzes (
                        session_id TEXT NOT NULL,
                        concept_id TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        questions JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (session_id, concept_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS quiz_attempts (
                        id BIGSERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        concept_id TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        score INTEGER NOT NULL,
                        total INTEGER NOT NULL,
                        hours_per_day REAL NOT NULL DEFAULT 1.0,
                        answers JSONB NOT NULL DEFAULT '[]'::jsonb,
                        study_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )

    @staticmethod
    def _fallback_questions(topic: str) -> List[Dict[str, Any]]:
        topic_lower = topic.lower()
        if "thermodynamic" in topic_lower or "heat" in topic_lower:
            return [
                {"id": "q1", "question": "A gas absorbs 500 J of heat and does 200 J of work on its surroundings. What is its change in internal energy?", "options": ["300 J", "700 J", "-300 J", "-700 J"], "answer": 0, "explanation": "Using ΔU = Q − W, ΔU = 500 − 200 = 300 J."},
                {"id": "q2", "question": "Which statement best describes the second law of thermodynamics?", "options": ["Entropy of an isolated system tends not to decrease", "Energy can be created from nothing", "All heat can be converted completely into work", "Temperature is independent of molecular motion"], "answer": 0, "explanation": "The second law gives the direction of spontaneous processes through entropy."},
                {"id": "q3", "question": "Why does a heat engine need both a hot reservoir and a cold reservoir?", "options": ["It needs a temperature difference to produce net work", "The cold reservoir creates energy", "The hot reservoir removes all entropy", "Both reservoirs must have the same temperature"], "answer": 0, "explanation": "A heat engine operates by transferring energy down a temperature gradient."},
                {"id": "q4", "question": "For an ideal gas in an isothermal expansion, what happens to its internal energy?", "options": ["It remains constant", "It always increases", "It always decreases", "It becomes equal to the work done"], "answer": 0, "explanation": "For an ideal gas, internal energy depends only on temperature, which is constant here."},
                {"id": "q5", "question": "What does the area under a pressure–volume graph represent during a process?", "options": ["Work done by the gas", "Change in temperature only", "Entropy in joules", "The gas mass"], "answer": 0, "explanation": "The work is W = ∫P dV, represented by the area under the P–V curve."},
            ]
        if "gravity" in topic_lower or "gravitation" in topic_lower:
            return [
                {"id": "q1", "question": "If the distance between two masses doubles, how does the gravitational force change?", "options": ["It becomes one-fourth as large", "It becomes twice as large", "It becomes half as large", "It stays the same"], "answer": 0, "explanation": "Newton's law gives F ∝ 1/r²."},
                {"id": "q2", "question": "Why do objects in free fall near Earth have approximately the same acceleration when air resistance is ignored?", "options": ["The ratio of gravitational force to inertial mass is g", "Heavier objects have no gravitational force", "Mass cancels from the gravitational force itself", "The objects have the same momentum"], "answer": 0, "explanation": "F = mg and a = F/m, so a = g regardless of mass."},
                {"id": "q3", "question": "What does the negative sign in gravitational potential energy usually indicate?", "options": ["The zero reference is chosen at infinite separation", "Gravity has negative mass", "Energy is destroyed", "The object must be moving downward"], "answer": 0, "explanation": "With U = 0 at infinity, bound masses have negative potential energy."},
                {"id": "q4", "question": "At which location is the gravitational field due to a spherically symmetric planet modeled as a point mass?", "options": ["Outside the planet", "Only at the surface", "Only at the center", "Nowhere"], "answer": 0, "explanation": "Outside a spherical mass, its field is equivalent to that of a point mass at its center."},
                {"id": "q5", "question": "What provides the centripetal acceleration for a satellite in a circular orbit?", "options": ["Gravitational force", "A continuous engine thrust", "The satellite's tangential velocity alone", "The absence of forces"], "answer": 0, "explanation": "Gravity continually changes the velocity direction and acts as the centripetal force."},
            ]
        return [
            {"id": "q1", "question": f"Which idea is most central to {topic}?", "options": ["A governing physical relationship", "A random fact", "A historical date", "A computer command"], "answer": 0, "explanation": "Physics concepts are organized around measurable quantities and governing relationships."},
            {"id": "q2", "question": f"When solving a problem about {topic}, what should you identify first?", "options": ["The system and known quantities", "The final number", "A memorized shortcut", "An unrelated example"], "answer": 0, "explanation": "Defining the system, quantities, and assumptions prevents incorrect reasoning."},
            {"id": "q3", "question": f"What makes an explanation of {topic} physically useful?", "options": ["It connects assumptions, quantities, and evidence", "It uses the most equations possible", "It avoids units", "It gives a number without reasoning"], "answer": 0, "explanation": "A sound explanation connects the model to evidence and assumptions."},
            {"id": "q4", "question": f"If your result for {topic} seems surprising, what is a good next step?", "options": ["Check units and limiting cases", "Ignore the result", "Change the answer until it looks familiar", "Remove the assumptions"], "answer": 0, "explanation": "Dimensions and limiting cases are powerful checks on physical reasoning."},
            {"id": "q5", "question": f"How should you communicate uncertainty about {topic}?", "options": ["State the assumptions and what would change the result", "Hide it", "Guess confidently", "Use no explanation"], "answer": 0, "explanation": "Physics conclusions are meaningful only within stated assumptions and limits."},
        ]

    def _generate_questions(self, topic: str, dialogue: str) -> List[Dict[str, Any]]:
        grounding = knowledge_engine.search_live_grounding(topic, max_results=3)
        prompt = f"""Create a 5-question multiple-choice physics quiz for the concept: {topic}.
Use this learner dialogue as context:
{dialogue[-5000:]}

Use these retrieved physics sources as factual grounding:
{grounding[:9000]}

Return strict JSON only in this shape: {{"questions":[...]}}. The questions array must contain exactly 5 items. Each item must contain id, question, options (exactly 4 strings), answer (zero-based integer), and explanation. Test this learner's conceptual understanding and likely misconceptions, not generic study habits or trivia. Every question must mention or clearly apply {topic}."""
        try:
            response = requests.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "format": "json", "stream": False, "options": {"temperature": 0.2}},
                timeout=18,
            )
            if response.status_code == 200:
                parsed = json.loads(response.json().get("response", "{}"))
                candidate_questions = parsed.get("questions", []) if isinstance(parsed, dict) else parsed
                if isinstance(candidate_questions, list) and len(candidate_questions) >= 3:
                    clean = []
                    for index, item in enumerate(candidate_questions[:5]):
                        if isinstance(item, dict) and len(item.get("options", [])) == 4:
                            clean.append({**item, "id": str(item.get("id", f"q{index + 1}")), "answer": int(item.get("answer", 0))})
                    if len(clean) >= 3:
                        return clean
        except Exception as exc:
            logger.info("Quiz generation fallback for %s: %s", topic, exc)
        return QuizService._fallback_questions(topic)

    @staticmethod
    def _is_generic_fallback(questions: Any) -> bool:
        first = questions[0] if isinstance(questions, list) and questions else {}
        text = str(first.get("question", "")).lower() if isinstance(first, dict) else ""
        return "which idea is most central" in text or "a random fact" in " ".join(str(x).lower() for x in first.get("options", []))

    def get_or_create_quiz(self, session_id: str, concept_id: str, topic: str, dialogue: str) -> Dict[str, Any]:
        if not self.db.enabled:
            questions = self._fallback_questions(topic)
            return {"concept_id": concept_id, "topic": topic, "questions": self.public_questions(questions)}
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT topic, questions FROM concept_quizzes WHERE session_id = %s AND concept_id = %s", (session_id, concept_id))
                existing = cursor.fetchone()
        if existing and not self._is_generic_fallback(existing["questions"]):
            return {"concept_id": concept_id, "topic": existing["topic"], "questions": self.public_questions(existing["questions"])}
        questions = self._generate_questions(topic, dialogue)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO concept_quizzes (session_id, concept_id, topic, questions) VALUES (%s, %s, %s, %s::jsonb) ON CONFLICT (session_id, concept_id) DO UPDATE SET topic = EXCLUDED.topic, questions = EXCLUDED.questions, created_at = NOW()", (session_id, concept_id, topic, json.dumps(questions)))
        return {"concept_id": concept_id, "topic": topic, "questions": self.public_questions(questions)}

    @staticmethod
    def public_questions(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{key: value for key, value in question.items() if key != "answer"} for question in questions]

    def submit(self, session_id: str, concept_id: str, answers: List[int], hours_per_day: float = 1.0) -> Dict[str, Any]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT topic, questions FROM concept_quizzes WHERE session_id = %s AND concept_id = %s", (session_id, concept_id))
                quiz = cursor.fetchone()
        if not quiz:
            raise ValueError("Quiz not found for this concept.")
        questions = quiz["questions"]
        score = sum(1 for index, question in enumerate(questions) if index < len(answers) and answers[index] == question.get("answer"))
        hours = max(0.25, min(float(hours_per_day or 1), 12.0))
        plan = self.generate_study_plan(quiz["topic"], score, len(questions), hours)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO quiz_attempts (session_id, concept_id, topic, score, total, hours_per_day, answers, study_plan) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)", (session_id, concept_id, quiz["topic"], score, len(questions), hours, json.dumps(answers), json.dumps(plan)))
        return {"concept_id": concept_id, "topic": quiz["topic"], "score": score, "total": len(questions), "percentage": round(score / len(questions) * 100), "study_plan": plan}

    def generate_study_plan(self, topic: str, score: int, total: int, hours: float) -> Dict[str, Any]:
        grounding = knowledge_engine.search_live_grounding(topic, max_results=3)
        prompt = f"""Create a practical, specific physics study plan for {topic}.
Quiz result: {score}/{total} ({round(score / max(total, 1) * 100)}%).
The learner can study {hours} hours per day.
Use this retrieved physics context:
{grounding[:7000]}

Return strict JSON only with title, goal, duration_days, and schedule.
The schedule must have one object per day with day, minutes, focus, activity, checkpoint, and blocks.
Make every day meaningfully different and sequential: prerequisite repair, concept model, worked example, misconception contrast, then transfer/retrieval as appropriate to the score.
Each blocks array should contain 2-4 timed activities whose minutes add up to the daily minutes.
Name the actual equations, physical quantities, assumptions, and observable checks for {topic}. Do not repeat generic phrases on every day."""
        try:
            response = requests.post(f"{settings.OLLAMA_BASE_URL}/api/generate", json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "format": "json", "stream": False, "options": {"temperature": 0.3}}, timeout=18)
            if response.status_code == 200:
                plan = json.loads(response.json().get("response", "{}"))
                if isinstance(plan, dict) and self._is_usable_plan(plan):
                    return plan
        except Exception as exc:
            logger.info("Study plan generation fallback for %s: %s", topic, exc)
        return self._fallback_study_plan(topic, score, total, hours)

    @staticmethod
    def _is_usable_plan(plan: Dict[str, Any]) -> bool:
        schedule = plan.get("schedule")
        if not isinstance(schedule, list) or len(schedule) < 3:
            return False
        activities = [str(day.get("activity", "")).strip().lower() for day in schedule if isinstance(day, dict)]
        return len(activities) >= 3 and len(set(activities)) >= min(3, len(activities))

    def _fallback_study_plan(self, topic: str, score: int, total: int, hours: float) -> Dict[str, Any]:
        days = 3 if score / max(total, 1) >= 0.7 else 5
        minutes = round(hours * 60)
        phases = [
            ("Repair prerequisites", f"Review the physical quantities, units, and baseline definitions needed for {topic}.", "List the quantities and units without notes."),
            ("Build the governing model", f"Derive the central relationship for {topic} from its assumptions and interpret every symbol.", "Explain what changes when one input is doubled."),
            ("Work a guided example", f"Solve one representative {topic} problem with knowns, equation, substitution, and units.", "Obtain a dimensionally consistent result."),
            ("Contrast a misconception", f"Compare a correct {topic} case with a tempting wrong case and identify the failing assumption.", "State why the wrong rule fails physically."),
            ("Transfer and retrieve", f"Solve a new {topic} context, then check limiting cases and units.", "Justify the model choice for a fresh problem."),
        ][:days]
        schedule = []
        for day, (focus, activity, checkpoint) in enumerate(phases, start=1):
            first = round(minutes * 0.2)
            second = round(minutes * 0.5)
            schedule.append({"day": day, "minutes": minutes, "focus": focus, "activity": activity, "checkpoint": checkpoint, "blocks": [{"minutes": first, "task": "Retrieve prior knowledge and write the known quantities."}, {"minutes": second, "task": activity}, {"minutes": minutes - first - second, "task": checkpoint}]})
        return {"title": f"{topic}: {days}-day targeted study plan", "goal": f"Move from a {score}/{total} diagnostic result to reliable problem solving by connecting the physical model, equations, assumptions, and evidence.", "duration_days": days, "schedule": schedule}

    def attempts(self, session_id: str) -> List[Dict[str, Any]]:
        if not self.db.enabled:
            return []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT concept_id, topic, score, total, hours_per_day, study_plan, created_at FROM quiz_attempts WHERE session_id = %s ORDER BY created_at DESC", (session_id,))
                attempts = []
                for row in cursor.fetchall():
                    row["study_plan"] = row["study_plan"] if self._is_usable_plan(row["study_plan"]) else self._fallback_study_plan(row["topic"], row["score"], row["total"], row["hours_per_day"])
                    row["created_at"] = row["created_at"].isoformat()
                    attempts.append(row)
                return attempts


quiz_service = QuizService()
quiz_service.ensure_schema()
