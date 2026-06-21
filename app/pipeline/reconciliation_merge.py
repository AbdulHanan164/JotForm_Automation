import json
import logging
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict, Any

from app.documents.contracts import FileAnswer
from app.documents import storage

logger = logging.getLogger("webhook.reconciliation")

class ClassificationResult(TypedDict):
    document_type: str  # "id_photo", "lease_contract", "arnona_bill", "corp_cert", "tabu", "signature", or ""
    confidence: float   # 0.0 to 1.0
    reason: str        # Explanation of decision
    classifier: str    # "FilenameClassifier" | "CheckboxClassifier" | "OpenAIVisionClassifier" | ...

class DocumentClassifier(ABC):
    @abstractmethod
    def classify(self, file_path: str, context: dict[str, Any] | None = None) -> ClassificationResult:
        pass

class FilenameClassifier(DocumentClassifier):
    """
    Upgraded FilenameClassifier — Phase 10A.

    Improvements over Phase 9:
      1. Hebrew normalization: strips RTL/LTR marks, normalises separators,
         resolves dot/space variants (ת.ז → תז, ת ז → תז).
      2. Hebrew abbreviation support: תז, ספח, ת"ז, ת.ז → id_photo.
      3. Extended document-type synonyms: water_meter, electricity_meter,
         gas_bill, gas_meter, tabu_document, sale_contract.
      4. Multi-word confidence scoring:
           STRONG (≥ 2 Hebrew words matched) → 0.95
           SINGLE Hebrew keyword              → 0.90
           English-only keyword               → 0.90
           No match                           → 0.00

    Confidence model
    ----------------
    A file auto-merges when confidence ≥ 0.90 and classifier == FilenameClassifier.
    Every rule below returns exactly 0.95 (multi-word) or 0.90 (single keyword).
    0.00 means no deterministic classification is possible.
    """

    # ── Normalisation helpers ───────────────────────────────────────────────

    # Unicode directional marks that sometimes wrap Hebrew text in URLs
    _BIDI_MARKS = "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"

    @staticmethod
    def _normalise(raw: str) -> str:
        """
        Return a clean, lower-cased search string from a raw filename.

        Steps:
          1. URL-decode (%XX sequences).
          2. Strip Unicode directional / bidi marks.
          3. Collapse underscores, hyphens, dots between Hebrew chars → space.
          4. Collapse runs of whitespace → single space.
          5. Lowercase (Hebrew characters are case-insensitive; Latin is lowercased).
          6. Produce a second form where "ת.ז" / "ת ז" / "ת\"ז" → "תז"
             (stored as a separate normalised token stream for abbreviation lookup).
        """
        from urllib.parse import unquote
        import unicodedata
        import re

        # 1. URL-decode
        s = unquote(raw)

        # 2. Strip bidi marks
        for ch in FilenameClassifier._BIDI_MARKS:
            s = s.replace(ch, "")

        # 3. Replace underscores and hyphens with spaces
        s = s.replace("_", " ").replace("-", " ")

        # 4. Collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()

        # 5. Lowercase
        s = s.lower()

        return s

    @staticmethod
    def _normalise_abbrevs(s: str) -> str:
        """
        Secondary normalisation: resolve common abbreviation forms so that
        'ת.ז', 'ת"ז', 'ת ז', 'ת/ז' all become 'תז'.
        """
        import re
        # ת.ז / ת"ז / ת'ז / ת/ז → תז
        s = re.sub(r'ת[.\"\'\\/\s]ז', 'תז', s)
        # ספ ח → ספח (rare but seen in scanned names)
        s = re.sub(r'ספ\s+ח', 'ספח', s)
        return s

    # ── Rule table ──────────────────────────────────────────────────────────
    # Each entry: (document_type, confidence, [keywords_that_must_appear_in_normalised_fn])
    # Keywords are OR-evaluated — first match wins.
    # Entries earlier in the list take priority.
    #
    # Confidence guide:
    #   0.95 — multi-word Hebrew phrase (very specific; very low false-positive rate)
    #   0.90 — single Hebrew keyword (specific; low false-positive rate)
    #   0.90 — English keyword (specific; low false-positive rate)
    #
    # All values ≥ 0.90 → auto-merge allowed.

    _RULES: list[tuple[str, float, list[str]]] = [
        # ── Identity documents ─────────────────────────────────────────────
        # Multi-word Hebrew phrases (0.95)
        ("id_photo", 0.95, ["תעודת זהות", "תז וספח", "תז וספח"]),
        ("id_photo", 0.95, ["צילום תז", "צילום ת.ז"]),
        # Single Hebrew keywords / abbreviations (0.90)
        ("id_photo", 0.90, ["תז", "ספח", "דרכון", "פספורט"]),
        # English keywords (0.90)
        ("id_photo", 0.90, ["passport", "zehut", "id card", "identity"]),

        # ── Lease contract ─────────────────────────────────────────────────
        # Multi-word (0.95)
        ("lease_contract", 0.95, ["חוזה שכירות", "חוזה מכר חתום", "הסכם שכירות"]),
        ("lease_contract", 0.95, ["סיום שכירות", "שכירות חתום", "חוזה חתום"]),
        # Single Hebrew (0.90)
        ("lease_contract", 0.90, ["חוזה", "שכירות", "הסכם", "השכרה"]),
        # English (0.90)
        ("lease_contract", 0.90, ["lease", "contract", "rental agreement", "tenancy"]),

        # ── Sale contract (separate doc type) ──────────────────────────────
        ("sale_contract", 0.95, ["חוזה מכר"]),
        ("sale_contract", 0.90, ["מכר", "רכישה"]),
        ("sale_contract", 0.90, ["sale", "purchase agreement"]),

        # ── Arnona (municipal tax) bill ─────────────────────────────────────
        ("arnona_bill", 0.95, ["חשבון ארנונה", "צילום ארנונה"]),
        ("arnona_bill", 0.90, ["ארנונה"]),
        ("arnona_bill", 0.90, ["arnona", "municipal tax"]),

        # ── Water ──────────────────────────────────────────────────────────
        ("water_meter", 0.95, ["קריאת מונה מים", "מונה מים"]),
        ("water_bill",  0.95, ["חשבון מים"]),
        ("water_bill",  0.90, ["מים"]),
        ("water_bill",  0.90, ["water bill", "water meter"]),

        # ── Electricity ────────────────────────────────────────────────────
        ("electricity_meter", 0.95, ["קריאת מונה חשמל", "מונה חשמל"]),
        ("electricity_bill",  0.95, ["חשבון חשמל"]),
        ("electricity_bill",  0.90, ["חשמל"]),
        ("electricity_bill",  0.90, ["electric", "electricity"]),

        # ── Gas ────────────────────────────────────────────────────────────
        ("gas_meter", 0.95, ["קריאת מונה גז", "מונה גז"]),
        ("gas_bill",  0.95, ["חשבון גז"]),
        ("gas_bill",  0.90, ["גז"]),
        ("gas_bill",  0.90, ["gas bill", "gas meter"]),

        # ── Tabu (land registry extract) ───────────────────────────────────
        ("tabu_document", 0.95, ["נסח טאבו", "נסח רשם הקרקעות"]),
        ("tabu_document", 0.90, ["טאבו", "נסח"]),
        ("tabu_document", 0.90, ["tabu", "land registry"]),

        # ── Corp cert ──────────────────────────────────────────────────────
        ("corp_cert", 0.95, ["תעודת התאגדות", "אישור התאגדות"]),
        ("corp_cert", 0.90, ["התאגדות", "עוסק מורשה"]),
        ("corp_cert", 0.90, ["corp", "company reg", "incorporation"]),

        # ── Signature ──────────────────────────────────────────────────────
        ("signature", 0.90, ["חתימה"]),
        ("signature", 0.90, ["signature", "signed"]),
    ]

    def classify(self, file_path: str, context: dict[str, Any] | None = None) -> ClassificationResult:
        filename = Path(file_path).name

        # Normalise
        norm = self._normalise(filename)
        norm_abbrev = self._normalise_abbrevs(norm)

        # Strip the file extension from the search string so that e.g.
        # "תז.pdf" doesn't confuse patterns that look for "ז"
        import re
        norm_nostem = re.sub(r'\.[a-z0-9]{2,5}$', '', norm_abbrev).strip()

        # Try each rule in priority order
        for doc_type, confidence, keywords in self._RULES:
            for kw in keywords:
                # Check both the extension-stripped form and the full form
                if kw in norm_abbrev or kw in norm_nostem:
                    matched_kw = kw
                    return {
                        "document_type": doc_type,
                        "confidence": confidence,
                        "reason": (
                            f"Matched '{matched_kw}' → {doc_type} "
                            f"(conf={confidence:.2f}) in '{filename}'"
                        ),
                        "classifier": "FilenameClassifier",
                    }

        return {
            "document_type": "",
            "confidence": 0.0,
            "reason": f"No keywords matched in filename '{filename}'",
            "classifier": "FilenameClassifier",
        }


class CheckboxClassifier(DocumentClassifier):
    def classify(self, file_path: str, context: dict[str, Any] | None = None) -> ClassificationResult:
        ctx = context or {}
        checklist_selections = ctx.get("checklist_selections", [])
        
        if not checklist_selections:
            return {
                "document_type": "",
                "confidence": 0.0,
                "reason": "No checklist selections available in context",
                "classifier": "CheckboxClassifier"
            }
            
        # Map selections to doc types
        mapped_types = []
        for opt in checklist_selections:
            opt_lower = opt.lower()
            if any(x in opt_lower for x in ["תז", "ת\"ז", "זהות", "ת.ז"]):
                mapped_types.append("id_photo")
            if any(x in opt_lower for x in ["חוזה", "שכירות", "מכר", "הסכם"]):
                mapped_types.append("lease_contract")
            if "ארנונה" in opt_lower:
                mapped_types.append("arnona_bill")
            if "התאגדות" in opt_lower:
                mapped_types.append("corp_cert")
            if "טאבו" in opt_lower:
                mapped_types.append("tabu")
                
        mapped_types = list(set(mapped_types))
        
        if len(mapped_types) == 1:
            doc_type = mapped_types[0]
            return {
                "document_type": doc_type,
                "confidence": 0.80,
                "reason": f"Single checklist selection type mapped: {doc_type}",
                "classifier": "CheckboxClassifier"
            }
            
        # Sequential fallback for generic file names if multiple selections exist
        filename = Path(file_path).name.lower()
        generic_keywords = ["whatsapp", "screenshot", "image", "img", "scan", "photo", "лрг", "дог", "тз", "קריאת מונה", "מונה"]
        is_generic = any(x in filename for x in generic_keywords) or len(filename) < 12
        
        if is_generic and mapped_types:
            # Look for index of this generic file in sequential generic files list
            generic_files = ctx.get("generic_files", [])
            if file_path in generic_files:
                idx = generic_files.index(file_path)
                if idx < len(mapped_types):
                    doc_type = mapped_types[idx]
                    return {
                        "document_type": doc_type,
                        "confidence": 0.80,
                        "reason": f"Sequential checklist fallback mapping: file {idx + 1} -> doc_type '{doc_type}'",
                        "classifier": "CheckboxClassifier"
                    }
                    
        return {
            "document_type": "",
            "confidence": 0.0,
            "reason": f"Ambiguous checklist mapping with choices: {mapped_types}",
            "classifier": "CheckboxClassifier"
        }

class GeminiVisionClassifier(DocumentClassifier):
    """
    Phase 10C — Gemini Flash Vision document classifier.

    Sends an image or PDF file to Google Gemini Flash Vision and returns a
    structured ClassificationResult.

    Behaviour
    ---------
    * Only activated when ``settings.gemini_api_key`` is non-empty.
    * If the API key is missing → returns confidence=0.0 (skip to next classifier).
    * If the API call fails (network, quota, timeout) → returns confidence=0.0
      so the file is routed to needs_review rather than crashing the pipeline.
    * Confidence threshold for auto-merge: ≥ 0.90 (enforced by ClassifierPipeline).

    Supported document types
    ------------------------
    id_photo, lease_contract, arnona_bill, water_bill, water_meter,
    electricity_bill, electricity_meter, gas_bill, gas_meter,
    tabu_document, sale_contract, corp_cert, signature

    ClassificationResult extensions
    --------------------------------
    In addition to the base fields the result includes:
      ``model``          — Gemini model name used (e.g. "gemini-2.5-flash")
      ``classified_at``  — ISO-8601 UTC timestamp of the API call
    These extra keys are stored verbatim in the manifest for audit trail.
    """

    # Gemini model to use.  gemini-2.5-flash gives the best price/accuracy ratio
    # for document vision tasks and supports Hebrew natively.
    MODEL_ID = "gemini-2.5-flash"

    # Supported file formats
    _SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".pdf"}

    # Canonical document types the model is allowed to return
    _VALID_TYPES = {
        "id_photo", "lease_contract", "arnona_bill",
        "water_bill", "water_meter",
        "electricity_bill", "electricity_meter",
        "gas_bill", "gas_meter",
        "tabu_document", "sale_contract",
        "corp_cert", "signature",
    }

    # Classification prompt — bilingual (Hebrew + English) for maximum accuracy
    # on Israeli real-estate documents.
    _PROMPT = """\
You are a document classification expert specialising in Israeli real-estate rental documents.
Examine the provided image or PDF and classify it into exactly ONE of the following document types:

  id_photo          — Israeli identity card (תעודת זהות / תז / ספח) or passport
  lease_contract    — Rental/lease agreement (חוזה שכירות / הסכם שכירות / חוזה מכר חתום)
  arnona_bill       — Municipal property tax bill (חשבון ארנונה)
  water_bill        — Water utility bill (חשבון מים)
  water_meter       — Photograph of a water meter reading (קריאת מונה מים / מונה מים)
  electricity_bill  — Electricity bill (חשבון חשמל / חברת חשמל)
  electricity_meter — Photograph of an electricity meter reading (קריאת מונה חשמל / מונה חשמל)
  gas_bill          — Gas utility bill (חשבון גז)
  gas_meter         — Photograph of a gas meter reading (קריאת מונה גז / מונה גז)
  tabu_document     — Land registry extract (נסח טאבו / נסח רשם המקרקעין)
  sale_contract     — Property purchase agreement (חוזה מכר / הסכם רכישה)
  corp_cert         — Company / association registration certificate (תעודת התאגדות)
  signature         — Standalone signature document or signature page

Respond with a JSON object only — no markdown, no extra text:
{
  "document_type": "<one of the types above>",
  "confidence": <0.0 to 1.0>,
  "reason": "<one-sentence explanation in English>"
}

Rules:
- If you cannot identify the document with confidence >= 0.70, set document_type to ""
  and confidence to the value you have.
- Never guess; return "" if genuinely uncertain.
- Focus on visible headers, logos, form structure, meter dials, and text content.
"""

    def classify(self, file_path: str, context: dict[str, Any] | None = None) -> ClassificationResult:
        from app.config import settings
        api_key = settings.gemini_api_key

        if not api_key:
            return {
                "document_type": "",
                "confidence": 0.0,
                "reason": "GeminiVisionClassifier skipped: GEMINI_API_KEY not configured",
                "classifier": "GeminiVisionClassifier",
            }

        path = Path(file_path)
        ext = path.suffix.lower()

        if ext not in self._SUPPORTED_EXTS:
            return {
                "document_type": "",
                "confidence": 0.0,
                "reason": f"GeminiVisionClassifier skipped: unsupported extension '{ext}'",
                "classifier": "GeminiVisionClassifier",
            }

        if not path.exists():
            return {
                "document_type": "",
                "confidence": 0.0,
                "reason": f"GeminiVisionClassifier skipped: file not found at '{file_path}'",
                "classifier": "GeminiVisionClassifier",
            }

        try:
            return self._call_gemini(api_key, path, ext)
        except Exception as exc:
            logger.warning(
                "GeminiVisionClassifier API error for '%s': %s — routing to needs_review",
                path.name, exc
            )
            return {
                "document_type": "",
                "confidence": 0.0,
                "reason": f"GeminiVisionClassifier API error: {exc}",
                "classifier": "GeminiVisionClassifier",
            }

    def _call_gemini(self, api_key: str, path: Path, ext: str) -> ClassificationResult:
        """Make the Gemini API call and parse the response."""
        import json as _json

        try:
            from google import genai
            from google.genai import types as genai_types
        except ImportError:
            return {
                "document_type": "",
                "confidence": 0.0,
                "reason": "google-genai package not installed; run: pip install google-genai",
                "classifier": "GeminiVisionClassifier",
            }

        # Determine MIME type
        mime_map = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".heic": "image/heic",
            ".webp": "image/webp", ".gif": "image/gif",
            ".pdf": "application/pdf",
        }
        mime_type = mime_map.get(ext, "image/jpeg")

        # Read file bytes
        file_bytes = path.read_bytes()

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=self.MODEL_ID,
            contents=[
                genai_types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                self._PROMPT,
            ],
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=512,  # Increased to 512 for a bit of buffer
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0)
            ),
        )

        raw_text = (response.text or "").strip()
        classified_at = datetime.now(timezone.utc).isoformat()

        # Strip markdown fences if the model added them
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        try:
            parsed = _json.loads(raw_text)
        except _json.JSONDecodeError as exc:
            logger.warning(
                "GeminiVisionClassifier: JSON parse error for '%s': %s — raw: %r",
                path.name, exc, raw_text[:200]
            )
            return {
                "document_type": "",
                "confidence": 0.0,
                "reason": f"Gemini returned unparseable response: {raw_text[:100]}",
                "classifier": "GeminiVisionClassifier",
            }

        doc_type   = str(parsed.get("document_type", "")).strip()
        confidence = float(parsed.get("confidence", 0.0))
        reason     = str(parsed.get("reason", "")).strip()

        # Validate document type against known set
        if doc_type and doc_type not in self._VALID_TYPES:
            logger.warning(
                "GeminiVisionClassifier: unknown type '%s' for '%s'; marking unclassified",
                doc_type, path.name
            )
            doc_type   = ""
            confidence = 0.0
            reason     = f"Gemini returned unknown document type; marking unclassified"

        return {
            "document_type": doc_type,
            "confidence": confidence,
            "reason": reason,
            "classifier": "GeminiVisionClassifier",
            "model": self.MODEL_ID,
            "classified_at": classified_at,
        }



class OpenAIVisionClassifier(DocumentClassifier):
    """
    Phase 10D — OpenAI Vision (GPT-4o) document classifier.
    Only triggered when settings.openai_api_key is set and Gemini is skipped or not confident.
    """
    MODEL_ID = "gpt-4o"
    _SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    _VALID_TYPES = GeminiVisionClassifier._VALID_TYPES
    _PROMPT = GeminiVisionClassifier._PROMPT

    def classify(self, file_path: str, context: dict[str, Any] | None = None) -> ClassificationResult:
        from app.config import settings
        api_key = settings.openai_api_key

        if not api_key:
            return {
                "document_type": "",
                "confidence": 0.0,
                "reason": "OpenAIVisionClassifier skipped: OPENAI_API_KEY not configured",
                "classifier": "OpenAIVisionClassifier",
            }

        path = Path(file_path)
        ext = path.suffix.lower()

        if ext not in self._SUPPORTED_EXTS:
            return {
                "document_type": "",
                "confidence": 0.0,
                "reason": f"OpenAIVisionClassifier skipped: unsupported extension '{ext}'",
                "classifier": "OpenAIVisionClassifier",
            }

        if not path.exists():
            return {
                "document_type": "",
                "confidence": 0.0,
                "reason": f"OpenAIVisionClassifier skipped: file not found at '{file_path}'",
                "classifier": "OpenAIVisionClassifier",
            }

        try:
            return self._call_openai(api_key, path, ext)
        except Exception as exc:
            logger.warning(
                "OpenAIVisionClassifier API error for '%s': %s — routing to needs_review",
                path.name, exc
            )
            return {
                "document_type": "",
                "confidence": 0.0,
                "reason": f"OpenAIVisionClassifier API error: {exc}",
                "classifier": "OpenAIVisionClassifier",
            }

    def _call_openai(self, api_key: str, path: Path, ext: str) -> ClassificationResult:
        import json as _json
        import base64
        try:
            from openai import OpenAI
        except ImportError:
            return {
                "document_type": "",
                "confidence": 0.0,
                "reason": "openai package not installed; run: pip install openai",
                "classifier": "OpenAIVisionClassifier",
            }

        # Determine MIME type
        mime_map = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
        }
        mime_type = mime_map.get(ext, "image/jpeg")

        file_bytes = path.read_bytes()
        base64_image = base64.b64encode(file_bytes).decode('utf-8')
        image_url = f"data:{mime_type};base64,{base64_image}"

        client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model=self.MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url,
                            },
                        },
                    ],
                }
            ],
            temperature=0.0,
            max_tokens=256,
            response_format={"type": "json_object"}
        )

        raw_text = (response.choices[0].message.content or "").strip()
        classified_at = datetime.now(timezone.utc).isoformat()

        # Parse JSON
        parsed = _json.loads(raw_text)

        doc_type   = str(parsed.get("document_type", "")).strip()
        confidence = float(parsed.get("confidence", 0.0))
        reason     = str(parsed.get("reason", "")).strip()

        if doc_type and doc_type not in self._VALID_TYPES:
            doc_type   = ""
            confidence = 0.0
            reason     = f"OpenAI returned unknown document type; marking unclassified"

        return {
            "document_type": doc_type,
            "confidence": confidence,
            "reason": reason,
            "classifier": "OpenAIVisionClassifier",
            "model": self.MODEL_ID,
            "classified_at": classified_at,
        }


class ClassifierPipeline(DocumentClassifier):
    """
    Phase 10C/D pipeline order:

      1. FilenameClassifier     — deterministic, zero cost, instant
         ↓ if confidence < 0.90
      2. GeminiVisionClassifier — AI vision, only when key is configured
         ↓ if confidence < 0.90 or key not set
      3. OpenAIVisionClassifier — AI vision fallback, only when key is configured
         ↓ if confidence < 0.90 or key not set
      4. CheckboxClassifier     — checklist inference fallback (always needs_review)

    Auto-merge is only triggered for results with confidence ≥ 0.90 from
    FilenameClassifier, GeminiVisionClassifier, or OpenAIVisionClassifier.
    CheckboxClassifier always caps at 0.80 → needs_review.
    """

    def __init__(self):
        self._filename_clf  = FilenameClassifier()
        self._gemini_clf    = GeminiVisionClassifier()
        self._openai_clf    = OpenAIVisionClassifier()
        self._checkbox_clf  = CheckboxClassifier()

    def classify(self, file_path: str, context: dict[str, Any] | None = None) -> ClassificationResult:
        # ── Stage 1: FilenameClassifier ──────────────────────────────────────
        res = self._filename_clf.classify(file_path, context)
        if res["confidence"] >= 0.90:
            return res

        # ── Stage 2: GeminiVisionClassifier ──────────────────────────────────
        gemini_res = self._gemini_clf.classify(file_path, context)
        if gemini_res["confidence"] >= 0.90:
            return gemini_res

        # ── Stage 3: OpenAIVisionClassifier ──────────────────────────────────
        openai_res = self._openai_clf.classify(file_path, context)
        if openai_res["confidence"] >= 0.90:
            return openai_res

        # ── Stage 4: CheckboxClassifier (always needs_review) ────────────────
        cb_res = self._checkbox_clf.classify(file_path, context)
        if cb_res["confidence"] > 0.0:
            return cb_res

        # Final fallback: return whatever FilenameClassifier gave (0.00)
        return res


# ── Document Merger ─────────────────────────────────────────────────────────

def download_and_merge_files(
    orig_sub_id: str,
    missing_sub_id: str,
    local_file_paths: list[str],
    checklist_selections: list[str]
) -> dict[str, Any]:
    """
    Classify local Missing Docs files, copy them to original submission folder,
    no-overwrite, and update original _manifest.json.
    """
    from app.config import settings
    orig_dir = settings.documents_dir / orig_sub_id
    orig_dir.mkdir(parents=True, exist_ok=True)
    
    # Load or create original manifest
    manifest_path = orig_dir / "_manifest.json"
    manifest_data = {}
    if manifest_path.exists():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass
            
    if "submission_id" not in manifest_data:
        manifest_data["submission_id"] = orig_sub_id
    if "documents" not in manifest_data:
        manifest_data["documents"] = {}
        
    # Classify files
    pipeline = ClassifierPipeline()
    generic_keywords = ["whatsapp", "screenshot", "image", "img", "scan", "photo", "лрг", "дог", "тз", "קריאת מונה", "מונה"]
    generic_files = []
    
    for f in local_file_paths:
        name = Path(f).name.lower()
        if any(gk in name for gk in generic_keywords) or len(name) < 12:
            generic_files.append(f)
            
    context = {
        "checklist_selections": checklist_selections,
        "generic_files": generic_files
    }
    
    for f_path in local_file_paths:
        src = Path(f_path)
        if not src.exists():
            continue
            
        res = pipeline.classify(f_path, context)
        doc_type = res["document_type"]
        ext = src.suffix.lower()
        
        # Decide status and target filename based on classifier type and confidence
        if doc_type:
            classifier_name = res.get("classifier")
            confidence = res.get("confidence", 0.0)
            
            # Auto-merge only allowed for FilenameClassifier or future AI classifiers with confidence >= 0.90
            is_auto_merge_classifier = classifier_name in (
                "FilenameClassifier", 
                "OpenAIVisionClassifier", 
                "NvidiaVisionClassifier", 
                "GeminiVisionClassifier"
            )
            
            if is_auto_merge_classifier and confidence >= 0.90:
                status = "present"
            else:
                status = "needs_review"
            stem = storage.filename_stem_for(doc_type)
            
            # Non-overwrite logic
            dest_path = orig_dir / f"{stem}{ext}"
            if dest_path.exists():
                idx = 1
                while True:
                    dest_path = orig_dir / f"{stem}_followup_{idx}{ext}"
                    if not dest_path.exists():
                        break
                    idx += 1
        else:
            status = "needs_review"
            from app.documents.downloader import _safe_filename
            safe_name = _safe_filename(src.stem)
            dest_path = orig_dir / "_unmapped" / f"{safe_name}{ext}"
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if dest_path.exists():
                idx = 1
                while True:
                    dest_path = orig_dir / "_unmapped" / f"{safe_name}_followup_{idx}{ext}"
                    if not dest_path.exists():
                        break
                    idx += 1
                    
        # Copy file
        shutil.copy2(src, dest_path)
        
        # Calculate SHA256
        content = dest_path.read_bytes()
        sha = storage.sha256_hex(content)
        
        file_entry = {
            "filename": dest_path.name,
            "local_path": str(dest_path),
            "sha256": sha,
            "size_bytes": len(content),
            "classifier": res["classifier"],
            "confidence": res["confidence"]
        }
        
        # Save to manifest
        if doc_type:
            doc_entry = manifest_data["documents"].setdefault(doc_type, {
                "status": "missing",
                "source_form": "251323124205946",
                "upload_date": datetime.now(timezone.utc).isoformat(),
                "files": []
            })
            
            # Status resolution: "present" takes priority. Once present, it stays present.
            if doc_entry["status"] != "present":
                doc_entry["status"] = status
                
            doc_entry["source_form"] = "251323124205946"
            doc_entry["upload_date"] = datetime.now(timezone.utc).isoformat()
            
            # Check if this file path is already in files list
            existing_paths = [x.get("local_path") for x in doc_entry["files"]]
            if str(dest_path) not in existing_paths:
                doc_entry["files"].append(file_entry)
        else:
            # Unmapped files recorded under special key
            unmapped_list = manifest_data.setdefault("unmapped_files", [])
            unmapped_list.append(file_entry)
            
    manifest_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    storage.write_manifest(orig_sub_id, manifest_data)
    return manifest_data

# ── Update Review Item ───────────────────────────────────────────────────────

def update_review_item_after_merge(orig_sub_id: str) -> None:
    """
    Loads ReviewItem, updates present documents, recalculates missing,
    re-drafts missing email, and saves it.
    """
    from app.review import queue as Q
    from app.mappers.models import BusinessSubmission
    from app.mappers.missing_detector import detect_missing
    from app.services.arnona.service import ArnonaService
    from app.documents.storage import hebrew_label_for
    
    item = Q.load(orig_sub_id)
    if not item:
        return
        
    # Read manifest
    from app.config import settings
    manifest_path = settings.documents_dir / orig_sub_id / "_manifest.json"
    if not manifest_path.exists():
        return
        
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return
        
    docs_manifest = manifest.get("documents", {})
    
    # Get status of each doc_type
    docs_bd = item.business_data.setdefault("documents", {})
    summary_docs = item.summary.setdefault("מסמכים", {})
    
    present_count = 0
    total_count = 0
    
    for doc_type in ["id_photo", "lease_contract", "signature", "arnona_bill", "corp_cert", "tabu"]:
        entry = docs_manifest.get(doc_type)
        if entry:
            status = entry.get("status")
            heb_label = hebrew_label_for(doc_type)
            
            if status == "present":
                docs_bd[doc_type] = "✅"
                if heb_label:
                    summary_docs[heb_label] = "✅"
                present_count += 1
            else:
                # needs_review or missing
                docs_bd[doc_type] = "❌"
                if heb_label:
                    summary_docs[heb_label] = "❌"
            total_count += 1
            
    if present_count == total_count:
        item.documents_status = "ready"
    elif present_count > 0:
        item.documents_status = "partial"
    else:
        item.documents_status = "failed"
        
    # Recalculate missing detection
    bs = BusinessSubmission.from_dict(item.business_data)
    bs.submission_id = orig_sub_id
    
    missing_res = detect_missing(bs)
    item.missing_docs = missing_res.get("missing_docs", [])
    
    # Re-draft email
    arnona_svc = ArnonaService()
    new_email = arnona_svc.draft_email(item.summary, {"missing_info": item.missing_info, "missing_docs": item.missing_docs})
    item.draft_email = new_email
    
    Q.save(item)
    logger.info("Updated original review item %s after document merge", orig_sub_id)

# ── Pipeline / Webhook triggers ──────────────────────────────────────────────

def reconcile_and_merge_for_original(orig_sub_id: str, parsed: dict[str, Any]) -> None:
    """
    Triggered during original pipeline. Checks local index for matching
    Missing Documents, copies files, updates parsed documents structure.
    """
    from app.pipeline.reconciliation import MissingDocsReconciler
    from app.pipeline.reconciliation_index import _load_index
    
    reconciler = MissingDocsReconciler()
    index = _load_index()
    
    # Find matches in local index
    matched_ids = []
    
    # Extract identity fields from original parsed
    answers = parsed.get("answers")
    if answers and isinstance(answers, dict):
        orig_mzk_raw = answers.get("184", {}).get("answer") or answers.get("291", {}).get("answer")
        orig_id_raw = answers.get("32", {}).get("answer")
        orig_email = (answers.get("30", {}).get("answer") or "").lower().strip()
        orig_phone = reconciler.normalize_phone(answers.get("208", {}).get("answer"))
    else:
        bd = parsed.get("_business") or parsed
        orig_mzk_raw = parsed.get("mzk_ref") or parsed.get("summary", {}).get("מידע_פנימי", {}).get("מספר_פנייה")
        incoming = bd.get("incoming_tenant") or {}
        orig_id_raw = incoming.get("id_number")
        orig_email = (incoming.get("email") or "").lower().strip()
        orig_phone = reconciler.normalize_phone(incoming.get("phone"))
        
    orig_mzk = reconciler.normalize_mzk(orig_mzk_raw)
    orig_id = reconciler.normalize_id(orig_id_raw)
    
    # Lookup index
    if orig_mzk and orig_mzk in index["mzk_index"]:
        matched_ids.extend(index["mzk_index"][orig_mzk])
    if orig_id and orig_id in index["id_index"]:
        matched_ids.extend(index["id_index"][orig_id])
    if orig_id and orig_email:
        # Check if matched by email
        for sub_id in index["email_index"].get(orig_email, []):
            sub_meta = index["submissions"].get(sub_id, {})
            if sub_meta.get("id_number") == orig_id:
                matched_ids.append(sub_id)
    if orig_id and orig_phone:
        # Check if matched by phone
        for sub_id in index["phone_index"].get(orig_phone, []):
            sub_meta = index["submissions"].get(sub_id, {})
            if sub_meta.get("id_number") == orig_id:
                matched_ids.append(sub_id)
                
    matched_ids = list(set(matched_ids))
    if not matched_ids:
        return
        
    for missing_id in matched_ids:
        sub_meta = index["submissions"].get(missing_id)
        if not sub_meta:
            continue
            
        logger.info("Found local reconciled match for %s -> missing doc submission %s", orig_sub_id, missing_id)
        
        # Download/Merge
        manifest = download_and_merge_files(
            orig_sub_id,
            missing_id,
            sub_meta["local_paths"],
            sub_meta["checklist_selections"]
        )
        
        # Update parsed documents in-memory
        for doc_type, entry in manifest.get("documents", {}).items():
            if entry.get("status") == "present":
                heb_label = hebrew_label_for(doc_type)
                if heb_label:
                    parsed.setdefault("documents", {})[heb_label] = {
                        "present": True,
                        "url": entry["files"][0]["source_url"] if entry["files"] else ""
                    }
                    
    # Re-build business data in parsed
    try:
        from app.mappers.business_mapper import build_from_parsed
        parsed["_business"] = build_from_parsed(parsed).to_dict()
    except Exception as exc:
        logger.warning("Failed to rebuild business data after merge: %s", exc)

def reconcile_and_merge_for_missing_docs(missing_sub_raw: dict[str, Any]) -> None:
    """
    Triggered when a new Missing Documents submission comes in.
    """
    from app.review import queue as Q
    from app.pipeline.reconciliation import MissingDocsReconciler
    
    sub_id = str(missing_sub_raw.get("id") or missing_sub_raw.get("submissionID"))
    
    # Save & Index first
    from app.pipeline.reconciliation_index import save_and_index_submission
    save_and_index_submission(missing_sub_raw)
    
    # Reload from index to get local file paths
    from app.pipeline.reconciliation_index import _load_index
    index = _load_index()
    sub_meta = index["submissions"].get(sub_id)
    if not sub_meta:
        return
        
    # Query actionable items in original review queue
    review_items = Q.load_all(limit=150)
    actionable_items = [item for item in review_items if item.is_actionable]
    
    reconciler = MissingDocsReconciler()
    for item in actionable_items:
        # Match original submission against the missing doc submission
        matches = reconciler.match_submission(item.to_dict(), [missing_sub_raw])
        if matches:
            logger.info("Found match for incoming missing docs submission %s -> original %s (confidence %s)",
                        sub_id, item.submission_id, matches[0]["confidence"])
            
            # Merge
            download_and_merge_files(
                item.submission_id,
                sub_id,
                sub_meta["local_paths"],
                sub_meta["checklist_selections"]
            )
            
            # Update original review queue item
            update_review_item_after_merge(item.submission_id)
