import csv
import io
import json
import os
from datetime import datetime
from typing import Dict, List

from flask import Flask, Response, flash, redirect, render_template, request, session, url_for

from ekilex_client import EkilexClient, normalize_words


app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-change-me')
client = EkilexClient()


EXPORT_COLUMNS = [
    'lemma',
    'part_of_speech',
    'translation',
    'level',
    'nimetav',
    'omastav',
    'osastav',
    'ma_inf',
    'da_inf',
    'extra_form',
    'pres_3sg',
    'past_3sg',
    'nud_form',
    'imper_2sg',
    'note',
]

POS_LABELS = {
    'nouns': 'Существительные',
    'adjectives': 'Прилагательные',
    'verbs': 'Глаголы',
    'other': 'Другие',
}


def group_results(results: List[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {
        'nouns': [],
        'adjectives': [],
        'verbs': [],
        'other': [],
    }

    for row in results:
        pos = row.get('part_of_speech', 'OTHER')

        if pos == 'NOUN':
            grouped['nouns'].append(row)
        elif pos == 'ADJ':
            grouped['adjectives'].append(row)
        elif pos == 'VERB':
            grouped['verbs'].append(row)
        else:
            grouped['other'].append(row)

    return grouped


@app.route('/', methods=['GET'])
def index():
    results = session.get('results', [])
    grouped = group_results(results) if results else None
    return render_template(
        'index.html',
        results=results,
        grouped=grouped,
        pos_labels=POS_LABELS,
    )

@app.route('/clear', methods=['POST'])
def clear_results():
    session.pop('results', None)
    session.pop('last_processed_at', None)
    flash('Список очищен.')
    return redirect(url_for('index'))


@app.route('/process', methods=['POST'])
def process_words():
    raw_text = request.form.get('words', '').strip()
    uploaded_file = request.files.get('word_file')

    imported_words: List[str] = []
    if uploaded_file and uploaded_file.filename:
        imported_words = parse_uploaded_file(uploaded_file.read(), uploaded_file.filename)

    words = normalize_words(raw_text)

    existing_lower = {w.lower() for w in words}
    for word in imported_words:
        if word.lower() not in existing_lower:
            words.append(word)
            existing_lower.add(word.lower())

    if not words:
        flash('Добавь слова в поле или загрузи CSV/JSON файл.')
        return redirect(url_for('index'))

    results = [client.get_word_data(word) for word in words]

    session['results'] = results
    session['last_processed_at'] = datetime.utcnow().isoformat()

    flash(f'Обработано слов: {len(results)}')
    return redirect(url_for('index'))


@app.route('/export/csv', methods=['GET'])
def export_csv():
    results = session.get('results', [])
    if not results:
        flash('Сначала обработай слова.')
        return redirect(url_for('index'))

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()

    for row in results:
        writer.writerow({column: row.get(column, '') for column in EXPORT_COLUMNS})

    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=estonian_words.csv'},
    )


@app.route('/export/json', methods=['GET'])
def export_json():
    results = session.get('results', [])
    if not results:
        flash('Сначала обработай слова.')
        return redirect(url_for('index'))

    payload = {
        'exported_at': datetime.utcnow().isoformat(),
        'count': len(results),
        'results': results,
    }

    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype='application/json; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=estonian_words.json'},
    )


def parse_uploaded_file(file_bytes: bytes, filename: str) -> List[str]:
    lower_name = filename.lower()

    if lower_name.endswith('.json'):
        return parse_json_words(file_bytes)

    if lower_name.endswith('.csv'):
        return parse_csv_words(file_bytes)

    flash('Поддерживаются только CSV и JSON файлы.')
    return []


def parse_json_words(file_bytes: bytes) -> List[str]:
    try:
        data = json.loads(file_bytes.decode('utf-8'))
    except Exception:
        flash('Не удалось прочитать JSON файл.')
        return []

    if isinstance(data, list):
        if all(isinstance(item, str) for item in data):
            return normalize_words('\n'.join(data))

        values = []
        for item in data:
            if isinstance(item, dict):
                candidate = item.get('word') or item.get('lemma') or item.get('estonian')
                if candidate:
                    values.append(str(candidate))

        return normalize_words('\n'.join(values))

    if isinstance(data, dict):
        words = data.get('words') or data.get('items') or []
        if isinstance(words, list):
            values = []

            for item in words:
                if isinstance(item, str):
                    values.append(item)
                elif isinstance(item, dict):
                    candidate = item.get('word') or item.get('lemma') or item.get('estonian')
                    if candidate:
                        values.append(str(candidate))

            return normalize_words('\n'.join(values))

    flash('JSON формат не распознан. Ожидается список слов или объект с полем words/items.')
    return []


def parse_csv_words(file_bytes: bytes) -> List[str]:
    try:
        text = file_bytes.decode('utf-8-sig')
    except Exception:
        flash('Не удалось прочитать CSV файл.')
        return []

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames:
        candidates = []

        for row in reader:
            for key in ['word', 'lemma', 'estonian', 'sõna', 'sona']:
                if key in row and row[key]:
                    candidates.append(row[key])
                    break

        if candidates:
            return normalize_words('\n'.join(candidates))

    lines = [line for line in text.splitlines() if line.strip()]
    if lines:
        return normalize_words('\n'.join(lines))

    return []


if __name__ == '__main__':
    app.run(debug=True)