"""
Internal contract types for the document-acquisition pipeline (Group A).

This module is the SINGLE boundary between the JotForm API response shape and
the rest of the document subsystem. Everything downstream — download, storage,
jobs, review update — consumes ``FileAnswer`` and never touches raw JotForm JSON.

If JotForm ever changes its response format, only the *producer* of
``FileAnswer`` (``app.integrations.jotform.client.get_submission_files``) needs
to change. Nothing that *consumes* ``FileAnswer`` is affected. That is what
keeps the API-shape assumption confined to one function.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FileAnswer:
    """One downloadable file reported by the JotForm Submission API.

    Attributes:
      question_id: Raw JotForm question id (e.g. ``"q35_input35"``). Provenance
                   only — never used for routing decisions.
      doc_type:    Canonical document type (e.g. ``"id_photo"``), or ``""`` when
                   the field is not mapped yet (stored under ``_unmapped/``).
      label:       Human label (typically Hebrew) for display / unmapped naming.
      url:         Finalized, downloadable URL.
    """
    question_id: str
    doc_type:    str
    label:       str
    url:         str

    @property
    def is_mapped(self) -> bool:
        return bool(self.doc_type)
