import os
import time
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()


class EkilexClient:
    BASE_URL = "https://ekilex.ee"

    def __init__(self) -> None:
        self.api_key = os.getenv("EKILEX_API_KEY", "").strip()
        self.session = requests.Session()

        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.headers = {
            "ekilex-api-key": self.api_key,
            "User-Agent": "estonian-word-tool/1.0",
        }

    def _get(self, path: str) -> Any:
        url = f"{self.BASE_URL}{path}"
        response = self.session.get(url, headers=self.headers, timeout=20)
        response.raise_for_status()
        return response.json()

    def get_word_data(self, lemma: str) -> Dict[str, Any]:
        try:
            # маленькая пауза, чтобы не долбить API слишком резко
            time.sleep(0.35)

            word_id = self.search_word(lemma)
            if not word_id:
                return self.empty_result(
                    lemma=lemma,
                    part_of_speech="OTHER",
                    note="Слово не найдено в Ekilex",
                )

            part_of_speech = self.detect_part_of_speech(word_id)
            details = self.get_word_details(word_id)
            paradigm = self.get_paradigm(word_id)

            translation = self.extract_translation(details)
            level = self.extract_level(details)
            forms = self.extract_forms(paradigm, part_of_speech)

            return {
                "lemma": lemma,
                "part_of_speech": part_of_speech,
                "translation": translation or "",
                "level": level or "",
                "note": "",
                **forms,
            }

        except requests.exceptions.RequestException as e:
            return self.empty_result(
                lemma=lemma,
                part_of_speech="OTHER",
                note=f"Network/API error: {str(e)}",
            )
        except Exception as e:
            return self.empty_result(
                lemma=lemma,
                part_of_speech="OTHER",
                note=f"Unexpected error: {str(e)}",
            )

    def search_word(self, lemma: str) -> Optional[int]:
        data = self._get(f"/api/word/search/{requests.utils.quote(lemma)}")
        words = data.get("words", [])
        if not words:
            return None

        estonian = next((w for w in words if w.get("lang") == "est"), None)
        if estonian:
            return estonian.get("wordId")

        return words[0].get("wordId")

    def get_word_details(self, word_id: int) -> Dict[str, Any]:
        return self._get(f"/api/word/details/{word_id}")

    def get_paradigm(self, word_id: int) -> List[Dict[str, Any]]:
        data = self._get(f"/api/paradigm/details/{word_id}")
        return data if isinstance(data, list) else []

    def detect_part_of_speech(self, word_id: int) -> str:
        details = self.get_word_details(word_id)

        for lexeme in details.get("lexemes", []):
            pos_list = lexeme.get("pos", [])
            if not pos_list:
                continue

            code = (pos_list[0].get("code") or "").lower()

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
        relation_details = details.get("wordRelationDetails", {})
        groups = relation_details.get("primaryWordRelationGroups", [])

        for group in groups:
            for member in group.get("members", []):
                if member.get("wordLang") == "rus" and member.get("wordValue"):
                    return self.strip_html(member["wordValue"])

        return None

    def extract_level(self, details: Dict[str, Any]) -> Optional[str]:
        for lexeme in details.get("lexemes", []):
            level = lexeme.get("lexemeProficiencyLevelCode")
            if level:
                return level
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

        if not paradigm_data:
            return forms

        paradigm = paradigm_data[0]
        paradigm_forms = paradigm.get("paradigmForms", [])

        if part_of_speech in ("NOUN", "ADJ"):
            for form in paradigm_forms:
                value = form.get("value", "")
                code = (form.get("morphCode", "") or "").lower()

                if code == "sgn" and not forms["nimetav"]:
                    forms["nimetav"] = value
                elif code == "sgg" and not forms["omastav"]:
                    forms["omastav"] = value
                elif code == "sgp" and not forms["osastav"]:
                    forms["osastav"] = value

        elif part_of_speech == "VERB":
            for form in paradigm_forms:
                value = form.get("value", "")
                code = form.get("morphCode", "")

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

    def empty_result(self, lemma: str, part_of_speech: str = "OTHER", note: str = "") -> Dict[str, Any]:
        return {
            "lemma": lemma,
            "part_of_speech": part_of_speech,
            "translation": "",
            "level": "",
            "note": note,
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

    @staticmethod
    def strip_html(text: str) -> str:
        import re
        return re.sub(r"<[^>]+>", "", text)
    
def normalize_words(raw_text: str) -> list[str]:
    if not raw_text:
        return []

    separators = [",", ";", "\t"]
    text = raw_text

    for sep in separators:
        text = text.replace(sep, "\n")

    words = []
    seen = set()

    for line in text.splitlines():
        word = line.strip()
        if not word:
            continue

        if word not in seen:
            seen.add(word)
            words.append(word)

    return words