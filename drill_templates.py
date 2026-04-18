"""
drill_templates.py
Строгие шаблоны упражнений. Каждый шаблон — контракт:
если requires не выполнен → шаблон не применяется к слову.
"""

from typing import Any, Dict, List

# ── GRAMMAR TOPICS → priority template ids ────────────────────
TOPIC_PRIORITY: Dict[str, List[str]] = {
    "партитив":       ["noun_osastav", "adj_osastav", "verb_da_inf"],
    "спряжение":      ["verb_pres_3sg", "verb_past_3sg", "verb_nud"],
    "инфинитив":      ["verb_ma_et", "verb_da_inf"],
    "падежи":         ["noun_omastav", "noun_osastav", "adj_osastav"],
    "прилагательные": ["adj_ru_et", "adj_osastav"],
    "глаголы":        ["verb_ma_et", "verb_da_inf", "verb_pres_3sg", "verb_past_3sg"],
    "существительные":["noun_ru_et", "noun_omastav", "noun_osastav"],
}

# ── TEMPLATE DEFINITIONS ──────────────────────────────────────
# prompt_tpl плейсхолдеры: {lemma} {translation} {ma_inf} {da_inf}
#   {nimetav} {omastav} {osastav} {pres_3sg} {past_3sg} {nud_form}
#   {imper_2sg} {extra_form}
# answer_field: имя поля в БД — это правильный ответ
# hint_tpl: показывается после 2й неудачной попытки
# grammar_note: показывается после неправильного ответа

TEMPLATES: List[Dict[str, Any]] = [

    # ════════════════════════════════════════
    # ROUND 1 — УЗНАВАНИЕ (difficulty=1)
    # ════════════════════════════════════════

    {
        "id":           "noun_ru_et",
        "pos":          ["NOUN"],
        "requires":     ["translation"],
        "difficulty":   1,
        "prompt_tpl":   "Переведи на эстонский: <b>{translation}</b>",
        "answer_field": "nimetav",   # fallback: lemma
        "hint_tpl":     "Это существительное. Первая буква: <b>{lemma[0]}</b>",
        "grammar_note": (
            "Именительный падеж (nimetav kääne) — базовая форма: "
            "<b>{lemma}</b> = {translation}"
        ),
    },
    {
        "id":           "verb_ru_et",
        "pos":          ["VERB"],
        "requires":     ["translation", "ma_inf"],
        "difficulty":   1,
        "prompt_tpl":   "Переведи на эстонский (ma-инфинитив): <b>{translation}</b>",
        "answer_field": "ma_inf",
        "hint_tpl":     "Первая буква: <b>{ma_inf[0]}</b>",
        "grammar_note": (
            "ma-инфинитив — базовая форма глагола: "
            "<b>{ma_inf}</b> = {translation}"
        ),
    },
    {
        "id":           "adj_ru_et",
        "pos":          ["ADJ"],
        "requires":     ["translation"],
        "difficulty":   1,
        "prompt_tpl":   "Переведи на эстонский: <b>{translation}</b>",
        "answer_field": "nimetav",
        "hint_tpl":     "Первая буква: <b>{lemma[0]}</b>",
        "grammar_note": (
            "Базовая форма прилагательного: <b>{nimetav}</b> = {translation}"
        ),
    },
    {
        "id":           "adv_ru_et",
        "pos":          ["ADV"],
        "requires":     ["translation"],
        "difficulty":   1,
        "prompt_tpl":   "Переведи на эстонский: <b>{translation}</b>",
        "answer_field": "lemma",
        "hint_tpl":     "Первая буква: <b>{lemma[0]}</b>",
        "grammar_note": "Наречие: <b>{lemma}</b> = {translation}",
    },
    {
        "id":           "other_ru_et",
        "pos":          ["PRON", "OTHER"],
        "requires":     ["translation"],
        "difficulty":   1,
        "prompt_tpl":   "Переведи на эстонский: <b>{translation}</b>",
        "answer_field": "lemma",
        "hint_tpl":     "Первая буква: <b>{lemma[0]}</b>",
        "grammar_note": "<b>{lemma}</b> = {translation}",
    },

    # ════════════════════════════════════════
    # ROUND 2 — ФОРМЫ (difficulty=2)
    # ════════════════════════════════════════

    {
        "id":           "noun_omastav",
        "pos":          ["NOUN"],
        "requires":     ["omastav", "translation", "nimetav"],
        "difficulty":   2,
        "prompt_tpl":   (
            "Поставь слово <b>{nimetav}</b> ({translation}) "
            "в родительный падеж <i>(omastav)</i>"
        ),
        "answer_field": "omastav",
        "hint_tpl":     "Omastav отвечает на вопрос «чей? чего?»",
        "grammar_note": (
            "Omastav (родительный): <b>{nimetav}</b> → <b>{omastav}</b>. "
            "Используется для принадлежности и после многих послелогов."
        ),
    },
    {
        "id":           "noun_osastav",
        "pos":          ["NOUN"],
        "requires":     ["osastav", "translation", "nimetav"],
        "difficulty":   2,
        "prompt_tpl":   (
            "Поставь слово <b>{nimetav}</b> ({translation}) "
            "в частичный падеж <i>(osastav / партитив)</i>"
        ),
        "answer_field": "osastav",
        "hint_tpl":     "Osastav используется после: loen, näen, tahan, ostan...",
        "grammar_note": (
            "Osastav (партитив): <b>{nimetav}</b> → <b>{osastav}</b>. "
            "Используется после большинства переходных глаголов."
        ),
    },
    {
        "id":           "verb_da_inf",
        "pos":          ["VERB"],
        "requires":     ["da_inf", "ma_inf", "translation"],
        "difficulty":   2,
        "prompt_tpl":   (
            "Дай da-инфинитив глагола <b>{ma_inf}</b> ({translation})"
        ),
        "answer_field": "da_inf",
        "hint_tpl":     "da-инфинитив используется после: tahan, võin, oskan...",
        "grammar_note": (
            "da-инфинитив: <b>{ma_inf}</b> → <b>{da_inf}</b>. "
            "Нужен после модальных глаголов: ma tahan <b>{da_inf}</b>."
        ),
    },
    {
        "id":           "verb_pres_3sg",
        "pos":          ["VERB"],
        "requires":     ["pres_3sg", "ma_inf", "translation"],
        "difficulty":   2,
        "prompt_tpl":   (
            "Проспрягай глагол <b>{ma_inf}</b> ({translation}): "
            "<i>ta / ta</i> ________ (3-е лицо, ед.ч., наст. время)"
        ),
        "answer_field": "pres_3sg",
        "hint_tpl":     "3-е лицо настоящего времени (единственное число)",
        "grammar_note": (
            "3sg настоящее: ta <b>{pres_3sg}</b>. "
            "Полная парадигма: ma {lemma[:-2]}n / sa {lemma[:-2]}d / ta <b>{pres_3sg}</b>"
        ),
    },
    {
        "id":           "verb_past_3sg",
        "pos":          ["VERB"],
        "requires":     ["past_3sg", "ma_inf", "translation"],
        "difficulty":   2,
        "prompt_tpl":   (
            "Проспрягай глагол <b>{ma_inf}</b> ({translation}): "
            "<i>ta / ta</i> ________ (3-е лицо, ед.ч., прошедшее время)"
        ),
        "answer_field": "past_3sg",
        "hint_tpl":     "Простое прошедшее время (lihtminevik)",
        "grammar_note": (
            "3sg прошедшее: ta <b>{past_3sg}</b>. "
            "Lihtminevik строится от основы прошедшего времени."
        ),
    },
    {
        "id":           "adj_omastav",
        "pos":          ["ADJ"],
        "requires":     ["omastav", "nimetav", "translation"],
        "difficulty":   2,
        "prompt_tpl":   (
            "Поставь прилагательное <b>{nimetav}</b> ({translation}) "
            "в родительный падеж <i>(omastav)</i>"
        ),
        "answer_field": "omastav",
        "hint_tpl":     "Прилагательное согласуется с существительным",
        "grammar_note": (
            "Omastav прилагательного: <b>{nimetav}</b> → <b>{omastav}</b>. "
            "Пример: {nimetav} raamat → {omastav} raamatu"
        ),
    },

    # ════════════════════════════════════════
    # ROUND 3 — ПРОДУКЦИЯ (difficulty=3)
    # ════════════════════════════════════════

    {
        "id":           "noun_osastav_context",
        "pos":          ["NOUN"],
        "requires":     ["osastav", "nimetav", "translation"],
        "difficulty":   3,
        "prompt_tpl":   (
            "Заполни пропуск: <i>Ma ostan ________</i> "
            "(я покупаю {translation})"
        ),
        "answer_field": "osastav",
        "hint_tpl":     "После «ostan» нужен партитив (osastav)",
        "grammar_note": (
            "После ostan (покупаю) → osastav: "
            "Ma ostan <b>{osastav}</b>."
        ),
    },
    {
        "id":           "verb_nud",
        "pos":          ["VERB"],
        "requires":     ["nud_form", "ma_inf", "translation"],
        "difficulty":   3,
        "prompt_tpl":   (
            "Дай -nud причастие глагола <b>{ma_inf}</b> ({translation})"
        ),
        "answer_field": "nud_form",
        "hint_tpl":     "-nud используется в перфекте: ma olen ___nud",
        "grammar_note": (
            "-nud причастие: <b>{ma_inf}</b> → <b>{nud_form}</b>. "
            "Перфект: ma olen <b>{nud_form}</b>."
        ),
    },
    {
        "id":           "verb_imper",
        "pos":          ["VERB"],
        "requires":     ["imper_2sg", "ma_inf", "translation"],
        "difficulty":   3,
        "prompt_tpl":   (
            "Дай повелительное наклонение (2sg) глагола "
            "<b>{ma_inf}</b> ({translation})"
        ),
        "answer_field": "imper_2sg",
        "hint_tpl":     "Повелительное наклонение — команда одному человеку",
        "grammar_note": (
            "Imperatív 2sg: <b>{imper_2sg}</b>! "
            "Используется для команд: <b>{imper_2sg}</b> kiiresti!"
        ),
    },
    {
        "id":           "adj_osastav",
        "pos":          ["ADJ"],
        "requires":     ["osastav", "nimetav", "translation"],
        "difficulty":   3,
        "prompt_tpl":   (
            "Заполни пропуск: <i>Ma loen ________ raamatut</i> "
            "(я читаю {translation} книгу)"
        ),
        "answer_field": "osastav",
        "hint_tpl":     (
            "После loen существительное в партитиве, "
            "прилагательное тоже меняется!"
        ),
        "grammar_note": (
            "Согласование в партитиве: "
            "{nimetav} raamat → <b>{osastav}</b> raamatut. "
            "Прилагательное меняется вместе с существительным."
        ),
    },
]

# ── LOOKUP BY ID ──────────────────────────────────────────────
TEMPLATE_BY_ID: Dict[str, Dict[str, Any]] = {t["id"]: t for t in TEMPLATES}


def get_applicable_templates(word: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Возвращает только те шаблоны, которые применимы к данному слову.
    Критерии:
      1. POS совпадает
      2. Все requires-поля непусты в word
    """
    pos = word.get("part_of_speech", "OTHER")
    result = []

    for tpl in TEMPLATES:
        # POS check
        if pos not in tpl["pos"]:
            continue

        # Requires check — все поля должны быть непустыми
        ok = True
        for field in tpl["requires"]:
            val = word.get(field, "")
            if not val or str(val).strip() == "":
                ok = False
                break

        if ok:
            result.append(tpl)

    return result


def render_prompt(tpl: Dict[str, Any], word: Dict[str, Any]) -> str:
    """Рендерит prompt_tpl подставляя поля слова."""
    ctx = {**word}
    # безопасно: если поле пустое, заменяем на "?"
    try:
        return tpl["prompt_tpl"].format(**ctx)
    except (KeyError, IndexError):
        return tpl["prompt_tpl"]


def render_grammar_note(tpl: Dict[str, Any], word: Dict[str, Any]) -> str:
    """Рендерит grammar_note с реальными формами слова."""
    ctx = {**word}
    try:
        return tpl["grammar_note"].format(**ctx)
    except (KeyError, IndexError):
        return tpl.get("grammar_note", "")


def render_hint(tpl: Dict[str, Any], word: Dict[str, Any]) -> str:
    """Рендерит hint_tpl."""
    ctx = {**word}
    try:
        return tpl["hint_tpl"].format(**ctx)
    except (KeyError, IndexError):
        return tpl.get("hint_tpl", "")


def get_expected_answer(tpl: Dict[str, Any], word: Dict[str, Any]) -> str:
    """
    Возвращает правильный ответ для шаблона.
    Fallback: если answer_field пустой — возвращает lemma.
    """
    field = tpl["answer_field"]
    value = word.get(field, "")
    if not value:
        value = word.get("lemma", "")
    return str(value).strip()