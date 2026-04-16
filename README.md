# Estonian Word Tool

Небольшой Flask-инструмент для учебной работы со словами эстонского языка.

## Что умеет
- принимать список слов вручную;
- импортировать слова из CSV и JSON;
- запрашивать данные из Ekilex;
- раскладывать результат по частям речи;
- экспортировать обработанные слова в CSV и JSON.


## Запуск

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Скопируй `.env.example` в `.env` и добавь API ключ.

```bash
# Windows PowerShell
$env:EKILEX_API_KEY="your_key"
$env:FLASK_SECRET_KEY="dev-secret"
python app.py
```

## Поддерживаемый импорт

### JSON
```json
["ema", "isa", "õppima"]
```

или

```json
{
  "words": [
    {"word": "ema"},
    {"lemma": "õppima"}
  ]
}
```

### CSV
Минимум одна колонка, например: `word`, `lemma`, `estonian`, `estonian`, `sõna`, `sona`.

## Замечание
Коды морфологических форм у Ekilex могут отличаться по типам лексем. Поэтому для части глаголов могут понадобиться дополнительные правила парсинга.
