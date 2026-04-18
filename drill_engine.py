"""
drill_engine.py
Строит сессию, валидирует ответы, вызывает AI когда нужно.
"""

import json
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from drill_templates import (
    TEMPLATE_BY_ID,
    TOPIC_PRIORITY,
    get_applicable_templates,
    get_expected_answer,
    render_grammar_note,
    render_hint,
    render_prompt,
)

logger = logging.getLogger(__name__)

MAX_EXERCISES = 40       # жёсткий лимит упражнений на сессию
MAX_RETRIES   = 2        # сколько раз показываем слово если ошибка
AI_TIMEOUT    = 12       # секунды на запрос к AI


# ── SESSION BUILDER ───────────────────────────────────────────

def build_session(
    words: List[Dict[str, Any]],
    list_id: int,
    list_name: str,
    grammar_topic: str = "",
) -> Dict[str, Any]:
    """
    Строит очередь упражнений из списка слов.
    Возвращает dict готовый к записи в Flask session.
    """
    priority_ids = TOPIC_PRIORITY.get(grammar_topic.lower().strip(), [])

    round1, round2, round3 = [], [], []

    for word in words:
        if word.get("status") == "error":
            continue  # пропускаем слова с ошибками

        applicable = get_applicable_templates(word)
        if not applicable:
            continue

        # Разбиваем по раундам
        r1 = [t for t in applicable if t["difficulty"] == 1]
        r2 = [t for t in applicable if t["difficulty"] == 2]
        r3 = [t for t in applicable if t["difficulty"] == 3]

        # Раунд 1: ровно 1 упражнение на слово
        if r1:
            tpl = r1[0]
            round1.append(_make_exercise(tpl, word))

        # Раунд 2: все применимые шаблоны
        for tpl in r2:
            round2.append(_make_exercise(tpl, word))

        # Раунд 3: все применимые шаблоны
        for tpl in r3:
            round3.append(_make_exercise(tpl, word))

    # Перемешиваем внутри раундов
    random.shuffle(round1)
    random.shuffle(round2)
    random.shuffle(round3)

    # Если есть грамматическая тема — поднять приоритетные шаблоны
    if priority_ids:
        round2 = _prioritize(round2, priority_ids)
        round3 = _prioritize(round3, priority_ids)

    exercises = round1 + round2 + round3

    # Жёсткий лимит
    if len(exercises) > MAX_EXERCISES:
        # Срезаем только Round3
        r3_count = len(round3)
        cut = len(exercises) - MAX_EXERCISES
        if cut <= r3_count:
            exercises = round1 + round2 + round3[:-cut]
        else:
            exercises = (round1 + round2)[:MAX_EXERCISES]

    return {
        "list_id":       list_id,
        "list_name":     list_name,
        "grammar_topic": grammar_topic,
        "exercises":     exercises,
        "current":       0,
        "results":       [],
        "started_at":    time.time(),
        "total":         len(exercises),
    }


def _make_exercise(tpl: Dict[str, Any], word: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "word_id":      word.get("id"),
        "lemma":        word.get("lemma", ""),
        "template_id":  tpl["id"],
        "prompt":       render_prompt(tpl, word),
        "answer":       _normalize(get_expected_answer(tpl, word)),
        "answer_field": tpl["answer_field"],
        "grammar_note": render_grammar_note(tpl, word),
        "hint":         render_hint(tpl, word),
        "forms":        _extract_forms(word),
        "difficulty":   tpl["difficulty"],
        "round":        tpl["difficulty"],
        "attempts":     0,
    }


def _extract_forms(word: Dict[str, Any]) -> Dict[str, str]:
    """Только заполненные формы — передаём в AI как контекст."""
    fields = [
        "lemma", "translation", "part_of_speech", "level",
        "nimetav", "omastav", "osastav",
        "ma_inf", "da_inf", "pres_3sg", "past_3sg",
        "nud_form", "imper_2sg", "extra_form",
    ]
    return {f: str(word[f]) for f in fields if word.get(f)}


def _prioritize(exercises: List[Dict], ids: List[str]) -> List[Dict]:
    """Поднимает приоритетные шаблоны в начало списка."""
    priority = [e for e in exercises if e["template_id"] in ids]
    rest     = [e for e in exercises if e["template_id"] not in ids]
    return priority + rest


# ── ANSWER VALIDATOR ──────────────────────────────────────────

def validate_answer(
    exercise: Dict[str, Any],
    student_answer: str,
    grammar_topic: str = "",
    use_ai: bool = True,
) -> Dict[str, Any]:
    """
    Валидирует ответ студента.
    Возвращает:
      {
        verdict:     "CORRECT" | "PARTIAL" | "WRONG",
        explanation: str,
        correct:     str,   # правильный ответ
        used_ai:     bool,
      }
    """
    normalized_student  = _normalize(student_answer)
    normalized_expected = exercise["answer"]

    # ── Шаг 1: точное совпадение ──────────────────────────────
    if normalized_student == normalized_expected:
        return {
            "verdict":     "CORRECT",
            "explanation": "",
            "correct":     exercise["answer"],
            "used_ai":     False,
        }

    # ── Шаг 2: мягкое совпадение (опечатка) ──────────────────
    if _is_typo(normalized_student, normalized_expected):
        return {
            "verdict":     "PARTIAL",
            "explanation": (
                f"Почти правильно! Небольшая опечатка. "
                f"Правильно: <b>{exercise['answer']}</b>"
            ),
            "correct":     exercise["answer"],
            "used_ai":     False,
        }

    # ── Шаг 3: AI (только для difficulty=3 или длинных ответов) ─
    if use_ai and (exercise["difficulty"] == 3 or len(student_answer.split()) > 1):
        ai_result = _call_ai(exercise, student_answer, grammar_topic)
        if ai_result:
            return ai_result

    # ── Шаг 4: WRONG ─────────────────────────────────────────
    return {
        "verdict":     "WRONG",
        "explanation": exercise.get("grammar_note", ""),
        "correct":     exercise["answer"],
        "used_ai":     False,
    }


def _normalize(text: str) -> str:
    """Нормализация для сравнения."""
    return text.strip().lower().rstrip(".")


def _levenshtein(a: str, b: str) -> int:
    """Расстояние Левенштейна."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0: return lb
    if lb == 0: return la

    prev = list(range(lb + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + cost))
        prev = curr
    return prev[lb]


def _is_typo(student: str, expected: str) -> bool:
    """True если это вероятно опечатка (distance=1 и слово достаточно длинное)."""
    if len(expected) < 4:
        return False
    return _levenshtein(student, expected) == 1


# ── AI VALIDATOR ──────────────────────────────────────────────

def _call_ai(
    exercise: Dict[str, Any],
    student_answer: str,
    grammar_topic: str,
) -> Optional[Dict[str, Any]]:
    """
    Вызывает Claude API для строгой проверки.
    Возвращает None если запрос неудачен.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set, skipping AI validation")
        return None

    topic_note = f"Грамматическая тема урока: {grammar_topic}." if grammar_topic else ""

    system_prompt = f"""Ты строгий эксперт по эстонской грамматике.
{topic_note}
Отвечай ТОЛЬКО валидным JSON без каких-либо других слов."""

    user_prompt = f"""Слово: {exercise['lemma']} ({exercise['forms'].get('translation', '')})
Все формы слова: {json.dumps(exercise['forms'], ensure_ascii=False)}
Задание: {exercise['prompt']}
Ожидаемый правильный ответ: {exercise['answer']}
Ответ ученика: {student_answer}

Верни JSON строго в этом формате:
{{
  "verdict": "CORRECT" или "PARTIAL" или "WRONG",
  "explanation": "1-2 предложения на русском языке объясняющие ошибку или подтверждающие правильность",
  "correct_form": "{exercise['answer']}"
}}

Правила:
- CORRECT: ответ правильный (допускается 1 опечатка)
- PARTIAL: смысл верный но форма неточная  
- WRONG: неправильная форма или не то слово
- explanation максимум 2 предложения, без лишних слов
- Если тема урока задана — фокусируй объяснение на ней"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 256,
                "system":     system_prompt,
                "messages":   [{"role": "user", "content": user_prompt}],
            },
            timeout=AI_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()

        # Убрать возможные markdown-обёртки
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)
        verdict = data.get("verdict", "WRONG").upper()
        if verdict not in ("CORRECT", "PARTIAL", "WRONG"):
            verdict = "WRONG"

        return {
            "verdict":     verdict,
            "explanation": data.get("explanation", ""),
            "correct":     data.get("correct_form", exercise["answer"]),
            "used_ai":     True,
        }

    except (requests.RequestException, json.JSONDecodeError, KeyError) as exc:
        logger.warning("AI validation failed: %s", exc)
        return None


# ── SESSION PROGRESS HELPERS ──────────────────────────────────

def record_result(
    drill_session: Dict[str, Any],
    exercise: Dict[str, Any],
    verdict: str,
    student_answer: str,
) -> None:
    """Записывает результат упражнения в сессию."""
    drill_session["results"].append({
        "word_id":      exercise["word_id"],
        "lemma":        exercise["lemma"],
        "template_id":  exercise["template_id"],
        "verdict":      verdict,
        "student":      student_answer,
        "correct":      exercise["answer"],
        "round":        exercise["round"],
        "difficulty":   exercise["difficulty"],
    })


def get_summary(drill_session: Dict[str, Any]) -> Dict[str, Any]:
    """Считает итоговую статистику сессии."""
    results  = drill_session.get("results", [])
    total    = len(results)
    correct  = sum(1 for r in results if r["verdict"] == "CORRECT")
    partial  = sum(1 for r in results if r["verdict"] == "PARTIAL")
    wrong    = sum(1 for r in results if r["verdict"] == "WRONG")
    accuracy = round(correct / total * 100) if total else 0

    # Слова с ошибками (≥1 WRONG)
    errors: Dict[str, Dict] = {}
    for r in results:
        if r["verdict"] == "WRONG":
            lemma = r["lemma"]
            if lemma not in errors:
                errors[lemma] = {"lemma": lemma, "count": 0}
            errors[lemma]["count"] += 1

    hard_words = sorted(errors.values(), key=lambda x: -x["count"])

    # По раундам
    by_round: Dict[int, Dict] = {}
    for r in results:
        rnd = r["round"]
        if rnd not in by_round:
            by_round[rnd] = {"total": 0, "correct": 0}
        by_round[rnd]["total"] += 1
        if r["verdict"] == "CORRECT":
            by_round[rnd]["correct"] += 1

    duration = int(time.time() - drill_session.get("started_at", time.time()))

    return {
        "total":       total,
        "correct":     correct,
        "partial":     partial,
        "wrong":       wrong,
        "accuracy":    accuracy,
        "hard_words":  hard_words,
        "duration":    duration,
        "by_round":    by_round,
    }