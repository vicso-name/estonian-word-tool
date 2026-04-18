import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

logger = logging.getLogger(__name__)


class EkilexError(Exception):
    pass


class EkilexConfigError(EkilexError):
    pass


class EkilexForbiddenError(EkilexError):
    pass


class EkilexNotFoundError(EkilexError):
    pass


class EkilexParseError(EkilexError):
    pass


@dataclass
class WordData:
    lemma: str = ""
    part_of_speech: str = "OTHER"
    translation: str = ""
    level: str = ""
    nimetav: str = ""
    omastav: str = ""
    osastav: str = ""
    ma_inf: str = ""
    da_inf: str = ""
    extra_form: str = ""
    pres_3sg: str = ""
    past_3sg: str = ""
    nud_form: str = ""
    imper_2sg: str = ""
    note: str = ""
    source: str = "ekilex"
    status: str = "ok"
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def normalize_words(raw_text: str) -> List[str]:
    if not raw_text:
        return []

    parts = re.split(r"[\n,;]+", raw_text)
    result: List[str] = []
    seen = set()

    for item in parts:
        word = item.strip()
        if not word:
            continue

        key = word.casefold()
        if key in seen:
            continue

        seen.add(key)
        result.append(word)

    return result


class EkilexClient:
    BASE_URL = "https://ekilex.ee"

    def __init__(self) -> None:
        self.api_key = os.getenv("EKILEX_API_KEY", "").strip()
        if not self.api_key:
            raise EkilexConfigError(
                "EKILEX_API_KEY is not configured. "
                "Generate API key in Ekilex profile and set it in environment variables."
            )

        self.session = requests.Session()
        self._cache: Dict[str, Dict[str, Any]] = {}

        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.headers = {
            "ekilex-api-key": self.api_key,
            "User-Agent": "estonian-word-tool/2.1",
            "Accept": "application/json, text/plain, */*",
        }

    def _get(self, path: str) -> Any:
        url = f"{self.BASE_URL}{path}"
        response = self.session.get(url, headers=self.headers, timeout=20)

        logger.info("GET %s -> %s", url, response.status_code)

        if response.status_code == 403:
            raise EkilexForbiddenError(
                f"403 Forbidden for {url}. Check EKILEX_API_KEY."
            )
        if response.status_code == 404:
            raise EkilexNotFoundError(f"404 for {url}")

        response.raise_for_status()

        try:
            return response.json()
        except ValueError as exc:
            snippet = response.text[:300].strip()
            raise EkilexParseError(
                f"Expected JSON for {url}, got non-JSON response. Snippet: {snippet}"
            ) from exc

    def get_word_data(self, lemma: str) -> Dict[str, Any]:
        normalized = lemma.strip()
        if not normalized:
            return self.empty_result(
                lemma="",
                note="Пустое слово.",
                error="empty_word",
            )

        cache_key = normalized.casefold()
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            # Небольшая пауза, чтобы не бомбить API слишком резко
            time.sleep(0.25)

            word_id = self.search_word(normalized)
            if not word_id:
                result = self.empty_result(
                    lemma=normalized,
                    note="Слово не найдено в Ekilex.",
                    error="not_found",
                )
                self._cache[cache_key] = result
                return result

            details = self.get_word_details(word_id)
            part_of_speech = self.detect_part_of_speech_from_details(details)
            paradigm = self.get_paradigm(word_id)

            translation = self.extract_translation(details)
            level = self.extract_level(details)
            forms = self.extract_forms(paradigm, part_of_speech)

            result = WordData(
                lemma=normalized,
                part_of_speech=part_of_speech,
                translation=translation or "",
                level=level or "",
                note="",
                source="ekilex_api",
                status="ok",
                error="",
                **forms,
            ).to_dict()

            self._cache[cache_key] = result
            return result

        except EkilexNotFoundError:
            result = self.empty_result(
                lemma=normalized,
                note=f'Слово "{normalized}" не найдено.',
                error="not_found",
            )
        except EkilexForbiddenError as exc:
            result = self.empty_result(
                lemma=normalized,
                note=str(exc),
                error="forbidden",
            )
        except requests.exceptions.RequestException as exc:
            result = self.empty_result(
                lemma=normalized,
                note=f"Network/API error: {exc}",
                error="request_error",
            )
        except Exception as exc:
            logger.exception('Unexpected error for "%s"', normalized)
            result = self.empty_result(
                lemma=normalized,
                note=f"Unexpected error: {exc}",
                error="unexpected_error",
            )

        self._cache[cache_key] = result
        return result

    def search_word(self, lemma: str) -> Optional[int]:
        data = self._get(f"/api/word/search/{requests.utils.quote(lemma)}")

        words: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            words = self._safe_list(data.get("words"))
            if not words:
                words = self._safe_list(data.get("results"))
            if not words:
                words = self._safe_list(data.get("items"))
        elif isinstance(data, list):
            words = [item for item in data if isinstance(item, dict)]

        if not words:
            return None

        lemma_cf = lemma.casefold()

        exact_est = next(
            (
                w
                for w in words
                if isinstance(w, dict)
                and w.get("lang") == "est"
                and str(w.get("wordValue") or w.get("value") or w.get("word") or "").casefold() == lemma_cf
                and w.get("wordId")
            ),
            None,
        )
        if exact_est:
            return self._to_int(exact_est.get("wordId"))

        estonian = next(
            (
                w
                for w in words
                if isinstance(w, dict) and w.get("lang") == "est" and w.get("wordId")
            ),
            None,
        )
        if estonian:
            return self._to_int(estonian.get("wordId"))

        first = next(
            (w for w in words if isinstance(w, dict) and w.get("wordId")),
            None,
        )
        if first:
            return self._to_int(first.get("wordId"))

        return None

    def get_word_details(self, word_id: int) -> Dict[str, Any]:
        data = self._get(f"/api/word/details/{word_id}")
        if not isinstance(data, dict):
            raise EkilexParseError(f"Word details response for {word_id} is not an object.")
        return data

    def get_paradigm(self, word_id: int) -> List[Dict[str, Any]]:
        data = self._get(f"/api/paradigm/details/{word_id}")
        return self._safe_list(data)

    def detect_part_of_speech_from_details(self, details: Dict[str, Any]) -> str:
        for lexeme in self._safe_list(details.get("lexemes")):
            if not isinstance(lexeme, dict):
                continue

            pos_list = self._safe_list(lexeme.get("pos"))
            if not pos_list:
                continue

            first_pos = pos_list[0] if pos_list else {}
            if not isinstance(first_pos, dict):
                continue

            code = str(first_pos.get("code") or "").lower()

            if code in ("v", "verb"):
                return "VERB"
            if code in ("adj", "a"):
                return "ADJ"
            if code in ("pron", "pro"):
                return "PRON"
            if code in ("s", "n", "noun", "subst"):
                return "NOUN"
            if code in ("adv",):
                return "ADV"

        return "OTHER"

    def extract_translation(self, details: Dict[str, Any]) -> Optional[str]:
        relation_details = self._safe_dict(details.get("wordRelationDetails"))
        groups = self._safe_list(relation_details.get("primaryWordRelationGroups"))

        for group in groups:
            if not isinstance(group, dict):
                continue

            members = self._safe_list(group.get("members"))
            for member in members:
                if not isinstance(member, dict):
                    continue

                if member.get("wordLang") == "rus" and member.get("wordValue"):
                    return self.strip_html(str(member["wordValue"]))

        return None

    def extract_level(self, details: Dict[str, Any]) -> Optional[str]:
        for lexeme in self._safe_list(details.get("lexemes")):
            if not isinstance(lexeme, dict):
                continue

            level = lexeme.get("lexemeProficiencyLevelCode")
            if level:
                return str(level)

        return None

    def extract_forms(self, paradigm_data: List[Dict[str, Any]], part_of_speech: str) -> Dict[str, str]:
        forms = {
            "nimetav": "",
            "omastav": "",
            "osastav": "",
            "ma_inf": "",
            "da_inf": "",
            "extra_form": "",
            "pres_3sg": "",
            "past_3sg": "",
            "nud_form": "",
            "imper_2sg": "",
        }

        paradigms = self._safe_list(paradigm_data)
        if not paradigms:
            return forms

        paradigm = paradigms[0] if isinstance(paradigms[0], dict) else {}
        paradigm_forms = self._safe_list(paradigm.get("paradigmForms"))

        if part_of_speech in ("NOUN", "ADJ"):
            for form in paradigm_forms:
                if not isinstance(form, dict):
                    continue

                value = str(form.get("value") or "")
                code = str(form.get("morphCode") or "").lower()

                if code == "sgn" and not forms["nimetav"]:
                    forms["nimetav"] = value
                elif code == "sgg" and not forms["omastav"]:
                    forms["omastav"] = value
                elif code == "sgp" and not forms["osastav"]:
                    forms["osastav"] = value

        elif part_of_speech == "VERB":
            for form in paradigm_forms:
                if not isinstance(form, dict):
                    continue

                value = str(form.get("value") or "")
                code = str(form.get("morphCode") or "")

                if code == "Sup" and not forms["ma_inf"]:
                    forms["ma_inf"] = value
                elif code == "Inf" and not forms["da_inf"]:
                    forms["da_inf"] = value
                elif code == "IndPrSg3" and not forms["pres_3sg"]:
                    forms["pres_3sg"] = value
                elif code == "IndIpfSg3" and not forms["past_3sg"]:
                    forms["past_3sg"] = value
                elif code == "PtsPtPs" and not forms["nud_form"]:
                    forms["nud_form"] = value
                elif code == "ImpPrSg2" and not forms["imper_2sg"]:
                    forms["imper_2sg"] = value
                elif code in ("PersPrIps", "PersPrImps", "SupIll", "SupIne", "SupEla") and not forms["extra_form"]:
                    forms["extra_form"] = value

        return forms

    def empty_result(
        self,
        lemma: str,
        note: str = "",
        error: str = "",
        part_of_speech: str = "OTHER",
    ) -> Dict[str, Any]:
        return WordData(
            lemma=lemma,
            part_of_speech=part_of_speech,
            translation="",
            level="",
            note=note,
            nimetav="",
            omastav="",
            osastav="",
            ma_inf="",
            da_inf="",
            extra_form="",
            pres_3sg="",
            past_3sg="",
            nud_form="",
            imper_2sg="",
            source="ekilex",
            status="error" if error else "ok",
            error=error,
        ).to_dict()

    @staticmethod
    def strip_html(text: str) -> str:
        return re.sub(r"<[^>]+>", "", text or "")

    @staticmethod
    def _safe_list(value: Any) -> List[Any]:
        return value if isinstance(value, list) else []

    @staticmethod
    def _safe_dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None