"""Persistent concept quizzes, scoring, and adaptive study plans."""

import json
import logging
import requests
from typing import Any, Dict, List

from .config import settings
from .postgres_memory import concept_memory
from .rag_engine import knowledge_engine
from .document_store import document_store, format_references

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
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS study_plan_progress (
                        session_id TEXT NOT NULL,
                        concept_id TEXT NOT NULL,
                        day INTEGER NOT NULL CHECK (day > 0),
                        completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (session_id, concept_id, day)
                    )
                    """
                )

    @staticmethod
    def _fallback_questions(topic: str) -> List[Dict[str, Any]]:
        # A quiz must come from retrieved sources and the LLM. Returning a
        # canned topic quiz here would hide retrieval/model failures from the
        # learner and recreate the generic-question problem.
        return []

    def _generate_questions(self, topic: str, dialogue: str) -> List[Dict[str, Any]]:
        grounding = self._grounding(topic, dialogue)
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
                        question = self._validated_question(item, index)
                        if question:
                            clean.append(question)
                    if len(clean) >= 3:
                        return clean
        except Exception as exc:
            logger.info("Quiz generation fallback for %s: %s", topic, exc)
        return QuizService._fallback_questions(topic)

    @staticmethod
    def _grounding(topic: str, dialogue: str = "") -> str:
        """The learner's uploaded material comes first, then web/local sources."""
        hits = document_store.search(f"{topic} {dialogue[-400:]}", k=4)
        web = knowledge_engine.search_live_grounding(topic, max_results=3)
        if hits:
            return "From the learner's uploaded documents:\n" + format_references(hits, 4000) + "\n\nOther sources:\n" + web
        return web

    @staticmethod
    def _validated_question(item: Any, index: int):
        """Accept a model-written question only if it is fully usable: text,
        exactly four options and an answer key that points at one of them.
        (An answer such as "B" or 4 used to crash scoring or make a question
        impossible to get right.)"""
        if not isinstance(item, dict):
            return None
        options = item.get("options")
        question = str(item.get("question", "")).strip()
        if not question or not isinstance(options, list) or len(options) != 4:
            return None
        answer = item.get("answer")
        if isinstance(answer, str) and answer.strip().upper() in {"A", "B", "C", "D"}:
            answer = "ABCD".index(answer.strip().upper())
        try:
            answer = int(answer)
        except (TypeError, ValueError):
            return None
        if not 0 <= answer <= 3:
            return None
        return {
            "id": str(item.get("id") or f"q{index + 1}"),
            "question": question,
            "options": [str(option) for option in options],
            "answer": answer,
            "explanation": str(item.get("explanation", "")),
        }

    def _require_db(self):
        if not self.db.enabled:
            raise RuntimeError("Quizzes need the PostgreSQL database. Set DATABASE_URL in backend/.env.")

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
        if not questions:
            raise RuntimeError(f"Grounded quiz generation failed for {topic}; no static quiz was used.")
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO concept_quizzes (session_id, concept_id, topic, questions) VALUES (%s, %s, %s, %s::jsonb) ON CONFLICT (session_id, concept_id) DO UPDATE SET topic = EXCLUDED.topic, questions = EXCLUDED.questions, created_at = NOW()", (session_id, concept_id, topic, json.dumps(questions)))
        return {"concept_id": concept_id, "topic": topic, "questions": self.public_questions(questions)}

    @staticmethod
    def public_questions(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{key: value for key, value in question.items() if key != "answer"} for question in questions]

    def submit(self, session_id: str, concept_id: str, answers: List[int], hours_per_day: float = 1.0) -> Dict[str, Any]:
        self._require_db()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT topic, questions FROM concept_quizzes WHERE session_id = %s AND concept_id = %s", (session_id, concept_id))
                quiz = cursor.fetchone()
        if not quiz:
            raise ValueError("Quiz not found for this concept.")
        questions = quiz["questions"]
        score = sum(1 for index, question in enumerate(questions) if index < len(answers) and answers[index] == question.get("answer"))
        try:
            hours = float(hours_per_day or 1)
        except (TypeError, ValueError):
            hours = 1.0
        if hours != hours:  # NaN
            hours = 1.0
        hours = max(0.25, min(hours, 12.0))
        plan = self.generate_study_plan(quiz["topic"], score, len(questions), hours)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO quiz_attempts (session_id, concept_id, topic, score, total, hours_per_day, answers, study_plan) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)", (session_id, concept_id, quiz["topic"], score, len(questions), hours, json.dumps(answers), json.dumps(plan)))
        return {"concept_id": concept_id, "topic": quiz["topic"], "score": score, "total": len(questions), "percentage": round(score / len(questions) * 100), "study_plan": plan, "completed_days": self.completed_days(session_id, concept_id)}

    def generate_study_plan(self, topic: str, score: int, total: int, hours: float) -> Dict[str, Any]:
        grounding = self._grounding(topic)
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
                if isinstance(plan, dict) and self._is_usable_plan(plan) and self._is_topic_specific_plan(topic, plan):
                    return plan
        except Exception as exc:
            logger.info("Study plan generation fallback for %s: %s", topic, exc)
        raise RuntimeError(f"Grounded study-plan generation failed for {topic}; no static plan was used.")

    @staticmethod
    def _is_usable_plan(plan: Dict[str, Any]) -> bool:
        schedule = plan.get("schedule")
        if not isinstance(schedule, list) or len(schedule) < 3:
            return False
        activities = [str(day.get("activity", "")).strip().lower() for day in schedule if isinstance(day, dict)]
        return len(activities) >= 3 and len(set(activities)) >= min(3, len(activities))

    @staticmethod
    def _is_topic_specific_plan(topic: str, plan: Dict[str, Any]) -> bool:
        text = json.dumps(plan).lower()
        topic_tokens = {token for token in topic.lower().replace('-', ' ').split() if len(token) > 3}
        return bool(topic_tokens.intersection(set(text.split())))

    def _fallback_study_plan(self, topic: str, score: int, total: int, hours: float) -> Dict[str, Any]:
        raise RuntimeError("Static study-plan fallback is disabled; plans must be generated from retrieved sources.")
        days = 3 if score / max(total, 1) >= 0.7 else 5
        minutes = round(hours * 60)
        if "thermodynamic" in topic.lower() or "heat" in topic.lower():
            phases = [
                ("State variables and system boundaries", "Define system, surroundings, state variables (P, V, T, U), and distinguish intensive from extensive properties using a sealed gas sample.", "Classify pressure, temperature, volume, and internal energy correctly."),
                ("First Law and sign convention", "Use ΔU = Q − W for a gas, track heat into the system and work done by the system, then solve a 500 J heat / 200 J work example.", "Calculate ΔU and explain the sign of Q and W."),
                ("Thermodynamic processes and P–V work", "Compare isothermal, isobaric, isochoric, and adiabatic processes; calculate work from the area under a P–V curve.", "Predict which quantities change in each process and justify the prediction."),
                ("Second Law and entropy", "Explain why heat flows spontaneously from hot to cold, calculate an entropy change qualitatively, and identify why no engine is 100% efficient.", "Use entropy to determine whether a proposed process is spontaneous."),
                ("Heat engines and transfer problem", "Analyze a heat-engine cycle with hot/cold reservoirs, efficiency η = W/Qh, and a new numerical scenario; check energy conservation and limiting cases.", "Solve a fresh engine problem and defend every assumption."),
            ][:days]
        elif "electric current" in topic.lower() or "electricity" in topic.lower() or "circuit" in topic.lower() or "ohm" in topic.lower():
            phases = [
                ("Charge and current", "Relate current to charge flow with I = ΔQ/Δt and identify the direction of conventional current in a simple circuit.", "Calculate charge transferred from a current-time interval."),
                ("Ohm's Law and resistance", "Use V = IR with measured voltage and resistance, and interpret the slope of a V–I graph.", "Solve a resistor problem and state what each variable means."),
                ("Series and parallel networks", "Reduce a circuit by comparing series and parallel resistance, then use current and voltage rules at each branch.", "Predict which branch carries more current and explain why."),
                ("Electrical power and energy", "Calculate P = VI, P = I²R, and P = V²/R for a device, then connect power to energy used over time.", "Check the unit conversion from watts to joules and watt-hours."),
                ("Kirchhoff transfer problem", "Solve a new multi-loop circuit using conservation of charge and energy, then check limiting cases and component ratings.", "Defend the current directions and verify the final voltage balance."),
            ][:days]
        else:
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

    def completed_days(self, session_id: str, concept_id: str) -> List[int]:
        if not self.db.enabled:
            return []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT day FROM study_plan_progress WHERE session_id = %s AND concept_id = %s ORDER BY day", (session_id, concept_id))
                return [row["day"] for row in cursor.fetchall()]

    def set_day_complete(self, session_id: str, concept_id: str, day: int, completed: bool) -> List[int]:
        try:
            day = int(day)
        except (TypeError, ValueError) as exc:
            raise ValueError("Study plan day must be a number.") from exc
        if day < 1:
            raise ValueError("Study plan day must be positive.")
        self._require_db()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if completed:
                    cursor.execute("INSERT INTO study_plan_progress (session_id, concept_id, day) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (session_id, concept_id, day))
                else:
                    cursor.execute("DELETE FROM study_plan_progress WHERE session_id = %s AND concept_id = %s AND day = %s", (session_id, concept_id, day))
        return self.completed_days(session_id, concept_id)

    def clear_study_plan(self, session_id: str, concept_id: str) -> None:
        if not self.db.enabled:
            return
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if concept_id:
                    cursor.execute("DELETE FROM study_plan_progress WHERE session_id = %s AND concept_id = %s", (session_id, concept_id))
                    cursor.execute("DELETE FROM quiz_attempts WHERE session_id = %s AND concept_id = %s", (session_id, concept_id))
                else:
                    cursor.execute("DELETE FROM study_plan_progress WHERE session_id = %s", (session_id,))
                    cursor.execute("DELETE FROM quiz_attempts WHERE session_id = %s", (session_id,))

    def attempts(self, session_id: str) -> List[Dict[str, Any]]:
        if not self.db.enabled:
            return []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT concept_id, topic, score, total, hours_per_day, study_plan, created_at FROM quiz_attempts WHERE session_id = %s ORDER BY created_at DESC", (session_id,))
                attempts = []
                for row in cursor.fetchall():
                    if row["study_plan"] and not (self._is_usable_plan(row["study_plan"]) and self._is_topic_specific_plan(row["topic"], row["study_plan"])):
                        row["study_plan"] = {"title": "Grounded study plan unavailable", "goal": "Submit a new concept quiz to generate a source-grounded study plan.", "duration_days": 0, "schedule": []}
                    row["completed_days"] = self.completed_days(session_id, row["concept_id"])
                    row["study_plan_cleared"] = not bool(row["study_plan"])
                    row["created_at"] = row["created_at"].isoformat()
                    attempts.append(row)
                return attempts


quiz_service = QuizService()
quiz_service.ensure_schema()
