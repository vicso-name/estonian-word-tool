import csv
import io
import json
import logging
import os
from datetime import datetime
from typing import Dict, List

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, session, url_for

from db import (
    create_list, delete_list, delete_word, get_all_lists, get_list,
    get_words, init_db, rename_list, update_word_field, upsert_words,
)
from ekilex_client import EkilexClient, EkilexConfigError, normalize_words


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

# Init DB on startup
init_db()

# Init Ekilex client
try:
    client = EkilexClient()
    EKILEX_CLIENT_ERROR = None
except EkilexConfigError as exc:
    client = None
    EKILEX_CLIENT_ERROR = str(exc)
    logger.error("Failed to initialize EkilexClient: %s", exc)


EXPORT_COLUMNS = [
    "lemma", "part_of_speech", "translation", "level",
    "nimetav", "omastav", "osastav",
    "ma_inf", "da_inf", "extra_form",
    "pres_3sg", "past_3sg", "nud_form", "imper_2sg",
    "note", "status", "error", "source",
]

POS_LABELS = {
    "nouns":      "Существительные",
    "adjectives": "Прилагательные",
    "verbs":      "Глаголы",
    "adverbs":    "Наречия",
    "pronouns":   "Местоимения",
    "other":      "Другие",
}

POS_ICONS = {
    "nouns":      "🏠",
    "adjectives": "🎨",
    "verbs":      "⚡",
    "adverbs":    "🔷",
    "pronouns":   "👤",
    "other":      "📦",
}


def group_results(results: List[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {
        k: [] for k in POS_LABELS
    }
    for row in results:
        pos = row.get("part_of_speech", "OTHER")
        if pos == "NOUN":
            grouped["nouns"].append(row)
        elif pos == "ADJ":
            grouped["adjectives"].append(row)
        elif pos == "VERB":
            grouped["verbs"].append(row)
        elif pos == "ADV":
            grouped["adverbs"].append(row)
        elif pos == "PRON":
            grouped["pronouns"].append(row)
        else:
            grouped["other"].append(row)
    return grouped


def process_batch(words: List[str]) -> List[dict]:
    results = []
    for word in words:
        results.append(client.get_word_data(word))
    return results


def make_stats(words: List[dict]) -> dict:
    return {
        "total": len(words),
        "ok":    sum(1 for r in words if r.get("status") == "ok"),
        "error": sum(1 for r in words if r.get("status") == "error"),
    }


# ── DASHBOARD ────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def dashboard():
    lists = get_all_lists()
    return render_template(
        "index.html",
        lists=lists,
        ekilex_client_error=EKILEX_CLIENT_ERROR,
    )


@app.route("/lists/create", methods=["POST"])
def create_word_list():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Введи название списка.")
        return redirect(url_for("dashboard"))
    list_id = create_list(name)
    return redirect(url_for("view_list", list_id=list_id))


@app.route("/lists/<int:list_id>/delete", methods=["POST"])
def delete_word_list(list_id: int):
    lst = get_list(list_id)
    if lst:
        delete_list(list_id)
        flash(f'Список «{lst["name"]}» удалён.')
    return redirect(url_for("dashboard"))


# ── LIST DETAIL ──────────────────────────────────────────────

@app.route("/list/<int:list_id>", methods=["GET"])
def view_list(list_id: int):
    lst = get_list(list_id)
    if not lst:
        flash("Список не найден.")
        return redirect(url_for("dashboard"))

    words = get_words(list_id)
    grouped = group_results(words) if words else None
    stats = make_stats(words)

    return render_template(
        "list.html",
        lst=lst,
        words=words,
        grouped=grouped,
        pos_labels=POS_LABELS,
        pos_icons=POS_ICONS,
        stats=stats,
        ekilex_client_error=EKILEX_CLIENT_ERROR,
    )


@app.route("/list/<int:list_id>/rename", methods=["POST"])
def rename_word_list(list_id: int):
    name = request.form.get("name", "").strip()
    if not name:
        return jsonify({"error": "empty name"}), 400
    rename_list(list_id, name)
    return jsonify({"ok": True, "name": name})


@app.route("/list/<int:list_id>/add-words", methods=["POST"])
def add_words_to_list(list_id: int):
    lst = get_list(list_id)
    if not lst:
        flash("Список не найден.")
        return redirect(url_for("dashboard"))

    if EKILEX_CLIENT_ERROR or client is None:
        flash(EKILEX_CLIENT_ERROR or "Ekilex client не настроен.")
        return redirect(url_for("view_list", list_id=list_id))

    raw_text = request.form.get("words", "").strip()
    uploaded_file = request.files.get("word_file")

    imported_words: List[str] = []
    if uploaded_file and uploaded_file.filename:
        imported_words = parse_uploaded_file(uploaded_file.read(), uploaded_file.filename)

    words = merge_words(raw_text=raw_text, imported_words=imported_words)

    if not words:
        flash("Нет слов для обработки.")
        return redirect(url_for("view_list", list_id=list_id))

    logger.info("Processing %s words for list %s", len(words), list_id)
    results = process_batch(words)
    upsert_words(list_id, results)

    ok = sum(1 for r in results if r.get("status") == "ok")
    err = len(results) - ok
    msg = f"Добавлено слов: {len(results)}."
    if err:
        msg += f" С ошибками: {err}."
    flash(msg)
    return redirect(url_for("view_list", list_id=list_id))


# ── WORD AJAX ────────────────────────────────────────────────

@app.route("/list/<int:list_id>/word/<int:word_id>/delete", methods=["POST"])
def delete_list_word(list_id: int, word_id: int):
    ok = delete_word(word_id, list_id)
    return jsonify({"ok": ok})


@app.route("/list/<int:list_id>/word/<int:word_id>/update", methods=["POST"])
def update_list_word(list_id: int, word_id: int):
    data = request.get_json(silent=True) or {}
    field = data.get("field", "")
    value = data.get("value", "")
    ok = update_word_field(word_id, list_id, field, value)
    if not ok:
        return jsonify({"error": "invalid field or word not found"}), 400
    return jsonify({"ok": True, "field": field, "value": value})


# ── EXPORT ───────────────────────────────────────────────────

@app.route("/list/<int:list_id>/export/csv")
def export_csv(list_id: int):
    lst = get_list(list_id)
    if not lst:
        flash("Список не найден.")
        return redirect(url_for("dashboard"))

    words = get_words(list_id)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for row in words:
        writer.writerow({col: row.get(col, "") for col in EXPORT_COLUMNS})

    filename = f"{lst['name'].replace(' ', '_')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/list/<int:list_id>/export/json")
def export_json(list_id: int):
    lst = get_list(list_id)
    if not lst:
        flash("Список не найден.")
        return redirect(url_for("dashboard"))

    words = get_words(list_id)
    payload = {
        "list_name":    lst["name"],
        "exported_at":  datetime.utcnow().isoformat(),
        "count":        len(words),
        "results":      words,
    }
    filename = f"{lst['name'].replace(' ', '_')}.json"
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── HELPERS ──────────────────────────────────────────────────

def merge_words(raw_text: str, imported_words: List[str]) -> List[str]:
    words = normalize_words(raw_text)
    existing = {w.casefold() for w in words}
    for word in imported_words:
        key = word.casefold()
        if key not in existing:
            words.append(word)
            existing.add(key)
    return words


def parse_uploaded_file(file_bytes: bytes, filename: str) -> List[str]:
    lower = filename.lower()
    if lower.endswith(".json"):
        return parse_json_words(file_bytes)
    if lower.endswith(".csv"):
        return parse_csv_words(file_bytes)
    flash("Поддерживаются только CSV и JSON файлы.")
    return []


def parse_json_words(file_bytes: bytes) -> List[str]:
    try:
        data = json.loads(file_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        flash(f"Ошибка чтения JSON: {exc}")
        return []

    if isinstance(data, list):
        if all(isinstance(i, str) for i in data):
            return normalize_words("\n".join(data))
        values = []
        for item in data:
            if isinstance(item, dict):
                c = item.get("word") or item.get("lemma") or item.get("estonian")
                if c:
                    values.append(str(c))
        return normalize_words("\n".join(values))

    if isinstance(data, dict):
        words = data.get("words") or data.get("items") or []
        if isinstance(words, list):
            values = []
            for item in words:
                if isinstance(item, str):
                    values.append(item)
                elif isinstance(item, dict):
                    c = item.get("word") or item.get("lemma") or item.get("estonian")
                    if c:
                        values.append(str(c))
            return normalize_words("\n".join(values))

    flash("JSON формат не распознан.")
    return []


def parse_csv_words(file_bytes: bytes) -> List[str]:
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("CSV файл должен быть в UTF-8.")
        return []

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames:
        candidates = []
        for row in reader:
            for key in ["word", "lemma", "estonian", "sõna", "sona"]:
                if key in row and row[key]:
                    candidates.append(row[key])
                    break
        if candidates:
            return normalize_words("\n".join(candidates))

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return normalize_words("\n".join(lines)) if lines else []


if __name__ == "__main__":
    app.run(debug=True)


# ── DRILL ROUTES ─────────────────────────────────────────────
from drill_engine import build_session, get_summary, record_result, validate_answer
from drill_templates import get_applicable_templates


@app.route("/list/<int:list_id>/drill", methods=["GET"])
def drill_start_page(list_id: int):
    lst = get_list(list_id)
    if not lst:
        flash("Список не найден.")
        return redirect(url_for("dashboard"))

    words    = get_words(list_id)
    ok_words = [w for w in words if w.get("status") != "error"]

    # Estimate exercise count
    estimate = 0
    for w in ok_words:
        applicable = get_applicable_templates(w)
        estimate += min(len(applicable), 5)  # roughly
    estimate = min(estimate, 40)

    return render_template(
        "drill_start.html",
        lst=lst,
        word_count=len(words),
        ok_count=len(ok_words),
        exercise_estimate=estimate,
        has_api_key=bool(os.getenv("ANTHROPIC_API_KEY")),
    )


@app.route("/list/<int:list_id>/drill/start", methods=["POST"])
def start_drill(list_id: int):
    lst = get_list(list_id)
    if not lst:
        flash("Список не найден.")
        return redirect(url_for("dashboard"))

    words         = get_words(list_id)
    grammar_topic = request.form.get("grammar_topic", "").strip()

    drill = build_session(
        words=words,
        list_id=list_id,
        list_name=lst["name"],
        grammar_topic=grammar_topic,
    )

    if not drill["exercises"]:
        flash("Недостаточно данных для дрилла. Убедись что слова имеют формы.")
        return redirect(url_for("view_list", list_id=list_id))

    session["drill"] = drill
    session.modified = True
    return redirect(url_for("drill_exercise", list_id=list_id))


@app.route("/list/<int:list_id>/drill/exercise", methods=["GET"])
def drill_exercise(list_id: int):
    drill = session.get("drill")
    if not drill or drill.get("list_id") != list_id:
        return redirect(url_for("drill_start_page", list_id=list_id))

    current = drill["current"]
    exercises = drill["exercises"]

    if current >= len(exercises):
        return redirect(url_for("drill_finish", list_id=list_id))

    exercise = exercises[current]

    return render_template(
        "drill.html",
        drill=drill,
        exercise=exercise,
        feedback=None,
    )


@app.route("/list/<int:list_id>/drill/answer", methods=["POST"])
def drill_answer(list_id: int):
    drill = session.get("drill")
    if not drill or drill.get("list_id") != list_id:
        return redirect(url_for("drill_start_page", list_id=list_id))

    current   = drill["current"]
    exercises = drill["exercises"]

    if current >= len(exercises):
        return redirect(url_for("drill_finish", list_id=list_id))

    exercise      = exercises[current]
    student_input = request.form.get("answer", "").strip()

    result = validate_answer(
        exercise=exercise,
        student_answer=student_input,
        grammar_topic=drill.get("grammar_topic", ""),
        use_ai=bool(os.getenv("ANTHROPIC_API_KEY")),
    )

    # Track attempts
    exercise["attempts"] = exercise.get("attempts", 0) + 1
    record_result(drill, exercise, result["verdict"], student_input)

    session["drill"] = drill
    session.modified = True

    return render_template(
        "drill.html",
        drill=drill,
        exercise=exercise,
        feedback=result,
    )


@app.route("/list/<int:list_id>/drill/next", methods=["POST"])
def drill_next(list_id: int):
    drill = session.get("drill")
    if not drill or drill.get("list_id") != list_id:
        return redirect(url_for("drill_start_page", list_id=list_id))

    drill["current"] = drill.get("current", 0) + 1
    session["drill"] = drill
    session.modified = True

    if drill["current"] >= drill["total"]:
        return redirect(url_for("drill_finish", list_id=list_id))

    return redirect(url_for("drill_exercise", list_id=list_id))


@app.route("/list/<int:list_id>/drill/finish", methods=["GET"])
def drill_finish(list_id: int):
    drill = session.get("drill")
    if not drill:
        return redirect(url_for("view_list", list_id=list_id))

    summary = get_summary(drill)
    return render_template(
        "drill_summary.html",
        drill=drill,
        summary=summary,
    )