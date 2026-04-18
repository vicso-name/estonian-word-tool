import csv
import io
import json
import logging
import os
from datetime import datetime
from typing import Dict, List

from flask import Flask, Response, flash, redirect, render_template, request, session, url_for

from ekilex_client import EkilexClient, EkilexConfigError, normalize_words


logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
)
logger = logging.getLogger(__name__)


app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-change-me')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024


try:
    client = EkilexClient()
    EKILEX_CLIENT_ERROR = None
except EkilexConfigError as exc:
    client = None
    EKILEX_CLIENT_ERROR = str(exc)
    logger.error('Failed to initialize EkilexClient: %s', exc)


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
    'status',
    'error',
    'source',
]

POS_LABELS = {
    'nouns': 'Существительные',
    'adjectives': 'Прилагательные',
    'verbs': 'Глаголы',
    'adverbs': 'Наречия',
    'pronouns': 'Местоимения',
    'other': 'Другие',
}


def group_results(results: List[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {
        'nouns': [],
        'adjectives': [],
        'verbs': [],
        'adverbs': [],
        'pronouns': [],
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
        elif pos == 'ADV':
            grouped['adverbs'].append(row)
        elif pos == 'PRON':
            grouped['pronouns'].append(row)
        else:
            grouped['other'].append(row)

    return grouped


def process_batch(words: List[str]) -> List[dict]:
    results: List[dict] = []
    for word in words:
        results.append(client.get_word_data(word))
    return results


@app.route('/', methods=['GET'])
def index():
    results = session.get('results', [])
    grouped = group_results(results) if results else None

    stats = {
        'total': len(results),
        'ok': sum(1 for r in results if r.get('status') == 'ok'),
        'error': sum(1 for r in results if r.get('status') == 'error'),
    }

    return render_template(
        'index.html',
        results=results,
        grouped=grouped,
        pos_labels=POS_LABELS,
        stats=stats,
        last_processed_at=session.get('last_processed_at'),
        ekilex_client_error=EKILEX_CLIENT_ERROR,
    )


@app.route('/clear', methods=['POST'])
def clear_results():
    session.pop('results', None)
    session.pop('last_processed_at', None)
    flash('Список очищен.')
    return redirect(url_for('index'))


@app.route('/process', methods=['POST'])
def process_words():
    if EKILEX_CLIENT_ERROR or client is None:
        flash(EKILEX_CLIENT_ERROR or 'Ekilex client is not configured.')
        return redirect(url_for('index'))

    raw_text = request.form.get('words', '').strip()
    uploaded_file = request.files.get('word_file')

    imported_words: List[str] = []
    if uploaded_file and uploaded_file.filename:
        imported_words = parse_uploaded_file(uploaded_file.read(), uploaded_file.filename)

    words = merge_words(raw_text=raw_text, imported_words=imported_words)

    if not words:
        flash('Добавь слова в поле или загрузи CSV/JSON файл.')
        return redirect(url_for('index'))

    logger.info('Processing %s words', len(words))
    results = process_batch(words)

    session['results'] = results
    session['last_processed_at'] = datetime.utcnow().isoformat()

    ok_count = sum(1 for r in results if r.get('status') == 'ok')
    error_count = len(results) - ok_count

    if error_count:
        first_error = next((r for r in results if r.get('status') == 'error'), None)
        if first_error:
            logger.warning('First error sample: %s', first_error)

        flash(f'Обработано слов: {len(results)}. Успешно: {ok_count}. С ошибками: {error_count}.')
    else:
        flash(f'Обработано слов: {len(results)}.')

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
        'success_count': sum(1 for r in results if r.get('status') == 'ok'),
        'error_count': sum(1 for r in results if r.get('status') == 'error'),
        'results': results,
    }

    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype='application/json; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=estonian_words.json'},
    )


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
    except UnicodeDecodeError:
        flash('JSON файл должен быть в UTF-8.')
        return []
    except json.JSONDecodeError:
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
    except UnicodeDecodeError:
        flash('CSV файл должен быть в UTF-8.')
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

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        return normalize_words('\n'.join(lines))

    return []


if __name__ == '__main__':
    app.run(debug=True)