"""
Unit tests for Phase 10C/D — GeminiVisionClassifier, OpenAIVisionClassifier, and ClassifierPipeline.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest.mock as mock
import pytest

import app.config
from app.pipeline.reconciliation_merge import (
    GeminiVisionClassifier,
    OpenAIVisionClassifier,
    ClassifierPipeline,
    FilenameClassifier,
    CheckboxClassifier,
)

@pytest.fixture
def temp_image_file(tmp_path) -> Path:
    p = tmp_path / "test_image.jpg"
    p.write_bytes(b"dummy image bytes")
    return p

@pytest.fixture
def temp_unsupported_file(tmp_path) -> Path:
    p = tmp_path / "test_doc.txt"
    p.write_bytes(b"dummy text bytes")
    return p


class TestGeminiVisionClassifier:

    def test_skipped_when_api_key_missing(self, temp_image_file):
        clf = GeminiVisionClassifier()
        with mock.patch.object(app.config.settings, "gemini_api_key", ""):
            res = clf.classify(str(temp_image_file))
            assert res["confidence"] == 0.0
            assert "skipped" in res["reason"]
            assert "not configured" in res["reason"]
            assert res["classifier"] == "GeminiVisionClassifier"

    def test_skipped_for_unsupported_extension(self, temp_unsupported_file):
        clf = GeminiVisionClassifier()
        with mock.patch.object(app.config.settings, "gemini_api_key", "mock_key"):
            res = clf.classify(str(temp_unsupported_file))
            assert res["confidence"] == 0.0
            assert "unsupported extension" in res["reason"]
            assert res["classifier"] == "GeminiVisionClassifier"

    def test_skipped_when_file_not_found(self, tmp_path):
        clf = GeminiVisionClassifier()
        non_existent = tmp_path / "does_not_exist.png"
        with mock.patch.object(app.config.settings, "gemini_api_key", "mock_key"):
            res = clf.classify(str(non_existent))
            assert res["confidence"] == 0.0
            assert "file not found" in res["reason"]
            assert res["classifier"] == "GeminiVisionClassifier"

    def test_handles_api_exception_safely(self, temp_image_file):
        clf = GeminiVisionClassifier()
        
        # Mock importing google.genai and Client creation throwing an error
        with mock.patch.object(app.config.settings, "gemini_api_key", "mock_key"):
            with mock.patch("google.genai.Client", side_effect=Exception("API limit exceeded")):
                res = clf.classify(str(temp_image_file))
                assert res["confidence"] == 0.0
                assert "API error" in res["reason"]
                assert "API limit exceeded" in res["reason"]
                assert res["classifier"] == "GeminiVisionClassifier"

    def test_successful_classification(self, temp_image_file):
        clf = GeminiVisionClassifier()

        mock_response = mock.MagicMock()
        mock_response.text = json.dumps({
            "document_type": "lease_contract",
            "confidence": 0.95,
            "reason": "Found lease agreement header and signatures."
        })

        mock_client = mock.MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with mock.patch.object(app.config.settings, "gemini_api_key", "mock_key"):
            with mock.patch("google.genai.Client", return_value=mock_client):
                res = clf.classify(str(temp_image_file))
                assert res["document_type"] == "lease_contract"
                assert res["confidence"] == 0.95
                assert res["reason"] == "Found lease agreement header and signatures."
                assert res["classifier"] == "GeminiVisionClassifier"
                assert res["model"] == "gemini-2.5-flash"
                assert "classified_at" in res

    def test_handles_json_parse_error_safely(self, temp_image_file):
        clf = GeminiVisionClassifier()

        mock_response = mock.MagicMock()
        # Invalid JSON returned by model
        mock_response.text = "This is not JSON text at all"

        mock_client = mock.MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with mock.patch.object(app.config.settings, "gemini_api_key", "mock_key"):
            with mock.patch("google.genai.Client", return_value=mock_client):
                res = clf.classify(str(temp_image_file))
                assert res["document_type"] == ""
                assert res["confidence"] == 0.0
                assert "unparseable response" in res["reason"]
                assert res["classifier"] == "GeminiVisionClassifier"

    def test_invalid_document_type_rejected(self, temp_image_file):
        clf = GeminiVisionClassifier()

        mock_response = mock.MagicMock()
        mock_response.text = json.dumps({
            "document_type": "totally_unknown_doc_type",
            "confidence": 0.98,
            "reason": "Looks like random paper."
        })

        mock_client = mock.MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with mock.patch.object(app.config.settings, "gemini_api_key", "mock_key"):
            with mock.patch("google.genai.Client", return_value=mock_client):
                res = clf.classify(str(temp_image_file))
                assert res["document_type"] == ""
                assert res["confidence"] == 0.0
                assert "unknown document type" in res["reason"]
                assert res["classifier"] == "GeminiVisionClassifier"


class TestOpenAIVisionClassifier:

    def test_skipped_when_api_key_missing(self, temp_image_file):
        clf = OpenAIVisionClassifier()
        with mock.patch.object(app.config.settings, "openai_api_key", ""):
            res = clf.classify(str(temp_image_file))
            assert res["confidence"] == 0.0
            assert "skipped" in res["reason"]
            assert "not configured" in res["reason"]
            assert res["classifier"] == "OpenAIVisionClassifier"

    def test_skipped_for_unsupported_extension(self, temp_unsupported_file):
        clf = OpenAIVisionClassifier()
        with mock.patch.object(app.config.settings, "openai_api_key", "mock_key"):
            res = clf.classify(str(temp_unsupported_file))
            assert res["confidence"] == 0.0
            assert "unsupported extension" in res["reason"]
            assert res["classifier"] == "OpenAIVisionClassifier"

    def test_skipped_when_file_not_found(self, tmp_path):
        clf = OpenAIVisionClassifier()
        non_existent = tmp_path / "does_not_exist.png"
        with mock.patch.object(app.config.settings, "openai_api_key", "mock_key"):
            res = clf.classify(str(non_existent))
            assert res["confidence"] == 0.0
            assert "file not found" in res["reason"]
            assert res["classifier"] == "OpenAIVisionClassifier"

    def test_handles_api_exception_safely(self, temp_image_file):
        clf = OpenAIVisionClassifier()
        with mock.patch.object(app.config.settings, "openai_api_key", "mock_key"):
            with mock.patch("openai.OpenAI", side_effect=Exception("OpenAI quota exceeded")):
                res = clf.classify(str(temp_image_file))
                assert res["confidence"] == 0.0
                assert "API error" in res["reason"]
                assert "OpenAI quota exceeded" in res["reason"]
                assert res["classifier"] == "OpenAIVisionClassifier"

    def test_successful_classification(self, temp_image_file):
        clf = OpenAIVisionClassifier()

        mock_choice = mock.MagicMock()
        mock_choice.message.content = json.dumps({
            "document_type": "arnona_bill",
            "confidence": 0.98,
            "reason": "Found property tax header."
        })
        mock_response = mock.MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = mock.MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with mock.patch.object(app.config.settings, "openai_api_key", "mock_key"):
            with mock.patch("openai.OpenAI", return_value=mock_client):
                res = clf.classify(str(temp_image_file))
                assert res["document_type"] == "arnona_bill"
                assert res["confidence"] == 0.98
                assert res["reason"] == "Found property tax header."
                assert res["classifier"] == "OpenAIVisionClassifier"
                assert res["model"] == "gpt-4o"
                assert "classified_at" in res


class TestClassifierPipeline:

    def test_pipeline_stops_at_filename_if_confident(self):
        pipeline = ClassifierPipeline()
        mock_fn_res = {"document_type": "arnona_bill", "confidence": 0.95, "classifier": "FilenameClassifier"}
        
        with mock.patch.object(FilenameClassifier, "classify", return_value=mock_fn_res) as mock_fn:
            with mock.patch.object(GeminiVisionClassifier, "classify") as mock_gemini:
                with mock.patch.object(OpenAIVisionClassifier, "classify") as mock_openai:
                    with mock.patch.object(CheckboxClassifier, "classify") as mock_cb:
                        res = pipeline.classify("dummy_path.jpg")
                        assert res == mock_fn_res
                        mock_fn.assert_called_once()
                        mock_gemini.assert_not_called()
                        mock_openai.assert_not_called()
                        mock_cb.assert_not_called()

    def test_pipeline_proceeds_to_gemini_if_filename_not_confident(self):
        pipeline = ClassifierPipeline()
        mock_fn_res = {"document_type": "", "confidence": 0.0, "classifier": "FilenameClassifier"}
        mock_gemini_res = {"document_type": "id_photo", "confidence": 0.92, "classifier": "GeminiVisionClassifier"}
        
        with mock.patch.object(FilenameClassifier, "classify", return_value=mock_fn_res) as mock_fn:
            with mock.patch.object(GeminiVisionClassifier, "classify", return_value=mock_gemini_res) as mock_gemini:
                with mock.patch.object(OpenAIVisionClassifier, "classify") as mock_openai:
                    with mock.patch.object(CheckboxClassifier, "classify") as mock_cb:
                        res = pipeline.classify("dummy_path.jpg")
                        assert res == mock_gemini_res
                        mock_fn.assert_called_once()
                        mock_gemini.assert_called_once()
                        mock_openai.assert_not_called()
                        mock_cb.assert_not_called()

    def test_pipeline_proceeds_to_openai_if_gemini_not_confident(self):
        pipeline = ClassifierPipeline()
        mock_fn_res = {"document_type": "", "confidence": 0.0, "classifier": "FilenameClassifier"}
        mock_gemini_res = {"document_type": "", "confidence": 0.0, "classifier": "GeminiVisionClassifier"}
        mock_openai_res = {"document_type": "lease_contract", "confidence": 0.96, "classifier": "OpenAIVisionClassifier"}
        
        with mock.patch.object(FilenameClassifier, "classify", return_value=mock_fn_res) as mock_fn:
            with mock.patch.object(GeminiVisionClassifier, "classify", return_value=mock_gemini_res) as mock_gemini:
                with mock.patch.object(OpenAIVisionClassifier, "classify", return_value=mock_openai_res) as mock_openai:
                    with mock.patch.object(CheckboxClassifier, "classify") as mock_cb:
                        res = pipeline.classify("dummy_path.jpg")
                        assert res == mock_openai_res
                        mock_fn.assert_called_once()
                        mock_gemini.assert_called_once()
                        mock_openai.assert_called_once()
                        mock_cb.assert_not_called()

    def test_pipeline_proceeds_to_checkbox_if_openai_not_confident(self):
        pipeline = ClassifierPipeline()
        mock_fn_res = {"document_type": "", "confidence": 0.0, "classifier": "FilenameClassifier"}
        mock_gemini_res = {"document_type": "", "confidence": 0.0, "classifier": "GeminiVisionClassifier"}
        mock_openai_res = {"document_type": "", "confidence": 0.0, "classifier": "OpenAIVisionClassifier"}
        mock_cb_res = {"document_type": "lease_contract", "confidence": 0.80, "classifier": "CheckboxClassifier"}
        
        with mock.patch.object(FilenameClassifier, "classify", return_value=mock_fn_res) as mock_fn:
            with mock.patch.object(GeminiVisionClassifier, "classify", return_value=mock_gemini_res) as mock_gemini:
                with mock.patch.object(OpenAIVisionClassifier, "classify", return_value=mock_openai_res) as mock_openai:
                    with mock.patch.object(CheckboxClassifier, "classify", return_value=mock_cb_res) as mock_cb:
                        res = pipeline.classify("dummy_path.jpg")
                        assert res == mock_cb_res
                        mock_fn.assert_called_once()
                        mock_gemini.assert_called_once()
                        mock_openai.assert_called_once()
                        mock_cb.assert_called_once()
