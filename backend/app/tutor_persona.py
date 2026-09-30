"""The tutor's voice and classroom habits.

This layer makes the voice agent behave like a human tutor rather than a
question-answering bot:

  * it knows the learner (name, what they worked on last time, their pace);
  * it understands classroom requests ("give me a hint", "say that again",
    "slow down", "explain it differently", "that's all for today");
  * it responds to frustration with reassurance and a smaller step;
  * its replies are written to be *heard*: short sentences, one idea at a
    time, a specific acknowledgement of what the learner said, and exactly
    one question to hand the turn back;
  * it closes a session with a spoken recap and a next step.
"""

import hashlib
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import LearnerProfile, LessonPhase

# ---------------------------------------------------------------- intents

_NAME = re.compile(r"\b(?:my name is|my name's|call me|you can call me)\s+([A-Za-z][A-Za-z'\-]{1,20})\.?(?:\s+([A-Za-z][A-Za-z'\-]{1,20}))?", re.I)
_NOT_NAMES = {"a", "an", "the", "not", "just", "very", "so", "confused", "ready", "done", "sure", "okay", "ok", "back"}

_INTENTS = [
    ("pace_slower", r"\b(slow(er)? down|(speak|talk|go)( a (bit|little))? slow(er|ly)|too fast|a bit slower|please slower|speak slower)\b"),
    ("pace_faster", r"\b(speed up|(speak|talk|go)( a (bit|little))? faster|too slow|a bit faster|speak faster)\b"),
    ("pace_normal", r"\b(normal speed|normal pace|regular speed)\b"),
    ("repeat", r"^(can you |could you |please )?(repeat( that| it| the question)?|say (that|it) again|pardon|sorry,? what|come again|one more time)\b|\b(repeat that|say that again|repeat the question)\b"),
    ("end_session", r"\b(that'?s (all|it) for today|let'?s stop( here)?|end (the )?(session|lesson)|i'?m done for today|stop the lesson|bye|goodbye|good night|see you (later|tomorrow|next time)|wrap (it )?up|summari[sz]e (the |our |today'?s )?(session|lesson))\b"),
    ("hint", r"\b(give me a hint|can i (get|have) a hint|(a |one )?hint,? please|i need a hint|hint please|any hints?|a clue|give me a clue)\b|^hint[.!?]?$"),
    ("explain_differently", r"\b(explain (it |that |this )?(differently|another way|in a different way|again|more simply|simpler)|i still don'?t (get|understand) (it|that)|say it (differently|another way)|use a different example)\b"),
    ("frustration", r"\b(i give up|this is (too |so )?(hard|difficult|confusing|impossible)|i'?m (so )?(stupid|dumb|hopeless|bad at (this|physics))|i hate (this|physics)|i can'?t do (this|it)|i'?ll never (get|understand) (this|it)|too hard for me)\b"),
    ("resume", r"^(yes|yeah|yep|sure|ok(ay)?)( please)?[.!]?$|^(yes|yeah|yep|sure|ok(ay)?|let'?s)?[ ,!.]*(let'?s )?(continue|pick (it )?up( where we left off)?|carry on|keep going|resume|go on|where we left off)\b"),
]


def detect_intent(text: str) -> Optional[str]:
    lowered = (text or "").strip().lower()
    for name, pattern in _INTENTS:
        if re.search(pattern, lowered):
            return name
    return None


def extract_name(text: str) -> Optional[str]:
    match = _NAME.search(text or "")
    if not match:
        return None
    first, second = match.group(1), match.group(2)
    if first.lower() in _NOT_NAMES:
        return None
    cap = lambda w: w[0].upper() + w[1:].lower()
    if first.lower().rstrip(".") in {"dr", "mr", "mrs", "ms", "miss", "prof", "professor", "sir"} and second:
        return f"{cap(first.rstrip('.'))} {cap(second)}"
    return cap(first)


def is_only_name_introduction(text: str) -> bool:
    """'Hi, I'm... my name is Priya' (nothing else to answer)."""
    stripped = _NAME.sub("", text or "")
    stripped = re.sub(r"\b(hi|hello|hey|and|i'?m|i am|so|well|please|thanks|thank you)\b", "", stripped, flags=re.I)
    return len(re.findall(r"[a-z]{3,}", stripped.lower())) <= 1


# ---------------------------------------------------------------- style

def pick(options: List[str], seed: str) -> str:
    """Deterministic variety: the same situation does not always get the
    same sentence, but tests stay reproducible."""
    digest = int(hashlib.md5((seed or "").encode("utf-8")).hexdigest(), 16)
    return options[digest % len(options)]


def time_greeting(hour: Optional[int] = None) -> str:
    hour = datetime.now().hour if hour is None else hour
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 17:
        return "Good afternoon"
    if 17 <= hour < 22:
        return "Good evening"
    return "Hello"


def display_name(profile: Optional[LearnerProfile]) -> Optional[str]:
    if not profile or not profile.learner_name or profile.learner_name.strip().lower() in {"student", "learner", ""}:
        return None
    return profile.learner_name.strip()


VOICE_STYLE_GUIDE = """
How to speak (your reply is read aloud by a text-to-speech voice):
- Talk like a patient, encouraging human tutor sitting next to the learner, not like a textbook.
- Start by reacting to the specific thing the learner just said (quote or paraphrase a few of their words) before teaching.
- Use short spoken sentences, one idea per sentence, 2 to 4 sentences in total.
- Praise effort and reasoning ("that's a careful way to think about it"), never intelligence, and never praise a wrong idea.
- When correcting, name what is right in their thinking first, then the part to rethink.
- No lists, headings, bullet points, markdown or emoji. Say equations in words where you can.
- End with exactly one clear question that hands the turn back to the learner.
{name_line}{affect_line}"""


def style_block(profile: Optional[LearnerProfile], affect: Optional[str] = None) -> str:
    name = display_name(profile)
    name_line = f"- The learner's name is {name}; use it at most once, naturally.\n" if name else ""
    affect_line = ""
    if affect == "frustration":
        affect_line = ("- The learner sounds frustrated. First normalise the struggle warmly in one sentence "
                       "(for example that this idea trips up most people at first), then offer a much smaller step.\n")
    return VOICE_STYLE_GUIDE.format(name_line=name_line, affect_line=affect_line)


def fit_for_voice(text: str, max_sentences: int = 5, max_chars: int = 650) -> str:
    """Keep model replies short enough to listen to. Long answers keep their
    opening and their closing question (the hand-back to the learner)."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) <= max_sentences:
        return text
    closing = sentences[-1] if sentences[-1].rstrip().endswith("?") else ""
    kept = sentences[: max_sentences - (1 if closing else 0)]
    if closing and closing not in kept:
        kept.append(closing)
    return " ".join(kept)


def speech_rate_for(profile: Optional[LearnerProfile], phase: Optional[LessonPhase]) -> int:
    """Percentage for the TTS voice: the learner's chosen pace, a touch slower
    when explaining new ideas."""
    base = profile.speech_rate if profile else 0
    if phase in (LessonPhase.TOPIC_TEACHING, LessonPhase.RESOLVING_DOUBT):
        base -= 5
    return max(-40, min(30, base))


# ---------------------------------------------------------------- canned tutor lines

def last_question(history: List[Dict[str, Any]]) -> Optional[str]:
    for turn in reversed(history or []):
        tutor = str(turn.get("tutor", "")).strip()
        if not tutor:
            continue
        questions = [s for s in re.split(r"(?<=[.!?])\s+", tutor) if s.strip().endswith("?")]
        return questions[-1] if questions else None
    return None


def pace_reply(intent: str, history: List[Dict[str, Any]], seed: str) -> str:
    opener = {
        "pace_slower": pick(["Of course, I'll slow down a little.", "Sure, let's take it slower."], seed),
        "pace_faster": pick(["Sure, I'll pick up the pace.", "Okay, a bit quicker then."], seed),
        "pace_normal": "Okay, back to my normal pace.",
    }[intent]
    previous = _last_tutor_text(history)
    return f"{opener} Here it is again: {previous}" if previous else f"{opener} What would you like to do next?"


_REPEAT_PREFIX = re.compile(r"^(sure\.\s+|(of course, i'll slow down a little|sure, let's take it slower|sure, i'll pick up the pace|okay, a bit quicker then|okay, back to my normal pace)\.\s+here it is again:\s+)", re.I)


def _last_tutor_text(history: List[Dict[str, Any]]) -> Optional[str]:
    for turn in reversed(history or []):
        tutor = str(turn.get("tutor", "")).strip()
        if tutor:
            # never stack "Sure. Sure. ..." when asked to repeat twice
            while _REPEAT_PREFIX.match(tutor):
                tutor = _REPEAT_PREFIX.sub("", tutor, count=1)
            return tutor
    return None


def repeat_reply(history: List[Dict[str, Any]]) -> str:
    previous = _last_tutor_text(history)
    if previous:
        return f"Sure. {previous}"
    return "Of course. I asked what you'd like to learn today. Which physics topic shall we explore?"


def name_reply(name: str, profile: LearnerProfile) -> str:
    if profile.current_topic and profile.current_phase != LessonPhase.GREETING:
        return f"Nice to meet you, {name}! Let's keep going with {profile.current_topic}. Where were we?"
    return f"Nice to meet you, {name}! What would you like to explore in physics today?"


def frustration_fallback(topic: str, seed: str) -> str:
    comfort = pick([
        "That's completely okay. This idea trips up almost everyone at first, and feeling stuck means you're really thinking about it.",
        "I hear you, and it's normal to feel that way. Struggling with this is exactly how the idea gets built.",
        "Let's pause for a second. You're not bad at this; it's a genuinely tricky idea, and we'll go one small step at a time.",
    ], seed)
    return f"{comfort} Let's make it smaller. Forget the numbers for a moment: in {topic or 'this problem'}, what is the one thing you're sure about?"


def greeting(profile: Optional[LearnerProfile], hour: Optional[int] = None) -> str:
    salutation = time_greeting(hour)
    name = display_name(profile)
    named = f"{salutation}, {name}!" if name else f"{salutation}!"
    if profile and profile.current_topic:
        verified = [c.concept_name for c in profile.concept_states.values() if c.recovery_verified]
        if verified and profile.current_topic in verified:
            last = f"Last time you mastered {profile.current_topic}, nice work."
        else:
            last = f"Last time we were working on {profile.current_topic}."
        return f"{named} Welcome back. {last} Shall we pick up where we left off, or try something new?"
    return f"{named} I'm your physics tutor. What would you like to explore today? You can name any topic, or ask me about something you've noticed in everyday life."


def recap(profile: LearnerProfile, since_index: int = 0) -> str:
    turns = [t for t in profile.conversation_history[since_index:] if t.get("user")]
    name = display_name(profile)
    thanks = f"Great work today, {name}." if name else "Great work today."
    if not turns:
        return f"{thanks} Whenever you're ready, just come back and tell me what you'd like to learn."
    topics: List[str] = []
    for turn in turns:
        topic = turn.get("topic")
        if topic and topic not in topics:
            topics.append(topic)
    if not topics and profile.current_topic:
        topics = [profile.current_topic]
    covered = ""
    if topics:
        covered = " We worked on " + (" and ".join(topics[:2]) if len(topics) <= 2 else ", ".join(topics[:-1]) + " and " + topics[-1]) + "."
    verified = [c.concept_name for c in profile.concept_states.values() if c.recovery_verified]
    struggles = [c.concept_name for c in profile.concept_states.values() if c.misconceptions_logged and not c.recovery_verified]
    strength = f" You showed you really understand {verified[-1]}, even on a brand-new problem." if verified else ""
    sound = sum(1 for t in turns if t.get("graded") and (t.get("reasoning_soundness") or 0) >= 0.85)
    if not strength and sound:
        strength = " Your reasoning got sharper as we went."
    if struggles:
        nxt = f" Next time, let's practise {struggles[-1]} a little more, starting with one quick challenge."
    elif topics:
        nxt = f" Next time, try the concept quiz on {topics[-1]} to lock it in."
    else:
        nxt = ""
    return f"{thanks}{covered}{strength}{nxt} See you soon!"


# ---------------------------------------------------------------- echo

def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def _norm_word(w: str) -> str:
    w = w.replace("'", "")
    return {"okay": "ok", "im": "i", "am": "i"}.get(w, w)


def _echo_run(heard: List[str], spoken: List[str]) -> int:
    """How many leading heard words follow the tutor's sentence in order
    (tolerating an occasional recognition slip). 0 if fewer than 5 match."""
    best = 0
    for start in range(len(spoken)):
        if spoken[start] != heard[0]:
            continue
        i, j, matched, budget, end = 0, start, 0, 1, 0
        while i < len(heard) and j < len(spoken):
            if heard[i] == spoken[j]:
                i, j, matched = i + 1, j + 1, matched + 1
                end = i                          # echo ends at the last exact match
                if matched % 5 == 0:
                    budget = 1
            elif budget and i + 1 < len(heard) and heard[i + 1] == spoken[j]:
                i, budget = i + 1, 0            # an extra word was heard
            elif budget and j + 1 < len(spoken) and heard[i] == spoken[j + 1]:
                j, budget = j + 1, 0            # a word was missed
            elif budget:
                i, j, budget = i + 1, j + 1, 0  # a word was misrecognised
            else:
                break
        if matched >= 5:
            best = max(best, end)
    return best


def strip_echo(heard: str, spoken: str) -> str:
    """Remove the tutor's own words picked up by the microphone: a leading run
    of at least four words that follows what the tutor just said *in order*.
    Answers that merely reuse the tutor's vocabulary ("the net force is zero"
    after "is the net force zero?") are kept. Returns '' when nothing but
    echo was heard. Mirrors stripEcho in the frontend."""
    heard = (heard or "").strip()
    tokens = heard.split()
    heard_words = [_norm_word(w) for w in _words(heard)]
    spoken_words = [_norm_word(w) for w in _words(spoken)]
    if len(heard_words) < 4 or not spoken_words:
        return heard
    removed = 0
    while True:
        run = _echo_run(heard_words[removed:], spoken_words) if len(heard_words) - removed >= 5 else 0
        if not run:
            break
        removed += run
    if not removed:
        return heard
    # map the number of removed words back onto the original tokens
    count, cut = 0, 0
    for index, token in enumerate(tokens):
        if count >= removed:
            break
        count += len(_words(token)) or 0
        cut = index + 1
    rest = " ".join(tokens[cut:]).strip()
    return rest if len(_words(rest)) >= 2 else ""
