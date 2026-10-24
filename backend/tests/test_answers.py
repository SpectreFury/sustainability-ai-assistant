import asyncio
import unittest
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from schemas.answers import (
    AnswerCalculationDraft,
    AnswerDraft,
    AnswerEvidenceDraft,
    AnswerKeyValueDraft,
)
from schemas.extraction import Locator, Segment
from services.answer_calculations import CalculationError, evaluate_expression
from services.answer_service import (
    AnswerDocument,
    _validate_draft,
    _answer_draft_from_gemini,
    answer_model_name,
    generate_answer,
    gemini_answer_schema,
)


def _document() -> AnswerDocument:
    return AnswerDocument(
        id=uuid4(),
        filename="Electricity bill.pdf",
        doc_type="electricity_bill",
        organisation="Example Facility",
        summary="A monthly electricity bill.",
        period_start="2024-04-01",
        period_end="2024-04-30",
        issues=[],
        facts=[
            {
                "key": "payable_amount",
                "label": "Payable amount",
                "value_text": "INR 631,510",
                "value_number": "631510",
                "unit": "INR",
                "origin": "reported",
                "verified": True,
                "locator": {"page": 1},
            }
        ],
        segments=[
            Segment(
                ordinal=0,
                locator=Locator(page=1),
                text="Payable by 30 May: INR 631,510.",
            )
        ],
    )


class AnswerCalculationTests(unittest.TestCase):
    def test_decimal_arithmetic_and_spreadsheet_ranges(self) -> None:
        segment = Segment(
            ordinal=0,
            locator=Locator(sheet="Monthly Summary 2026", cell_range="A1:B3"),
            text="A1=Month | B1=Cost\nA2=January | B2=100\nA3=February | B3=200",
            cells={"B2": 100.0, "B3": 200.0},
        )

        self.assertEqual(evaluate_expression("112500 + 7500", []), Decimal("120000"))
        self.assertEqual(
            evaluate_expression(
                "SUM('Monthly Summary 2026'!B2:B3)",
                [segment],
            ),
            Decimal("300.0"),
        )
        self.assertEqual(evaluate_expression("ROUND(10 / 3, 2)", []), Decimal("3.33"))

    def test_calculator_rejects_arbitrary_python_and_division_by_zero(self) -> None:
        with self.assertRaises(CalculationError):
            evaluate_expression("__import__('os').system('id')", [])
        with self.assertRaises(CalculationError):
            evaluate_expression("5 / 0", [])


class AnswerValidationTests(unittest.TestCase):
    def test_valid_citation_is_verified_and_decimal_values_remain_exact(self) -> None:
        document = _document()
        draft = AnswerDraft(
            status="answered",
            answer="INR 631,510 is payable by the due date [E1].",
            key_values=[
                AnswerKeyValueDraft(
                    label="Payable by the due date",
                    value="631510",
                    value_text="INR 631,510",
                    unit="INR",
                    period="30 May 2024",
                    origin="reported",
                    evidence_ids=["E1"],
                )
            ],
            evidence=[
                AnswerEvidenceDraft(
                    id="E1",
                    document_id=document.id,
                    page=1,
                    quote="Payable by 30 May: INR 631,510.",
                )
            ],
        )

        content, status = _validate_draft(draft, [document], "gemini-answer-test")

        self.assertEqual(status, "answered")
        self.assertTrue(content.evidence[0].verified)
        self.assertEqual(content.key_values[0].value, "631510")
        self.assertTrue(content.key_values[0].verified)
        self.assertIn("631,510", content.evidence[0].source_preview)

    def test_unverified_evidence_and_mismatched_math_downgrade_answer(self) -> None:
        document = _document()
        draft = AnswerDraft(
            status="answered",
            answer="The checked total is 900 [E1].",
            key_values=[],
            calculations=[
                AnswerCalculationDraft(
                    id="C1",
                    description="Add the two source values.",
                    expression="400 + 400",
                    result="900",
                    evidence_ids=["E1"],
                )
            ],
            evidence=[
                AnswerEvidenceDraft(
                    id="E1",
                    document_id=document.id,
                    page=1,
                    quote="Unprinted amount: 900",
                )
            ],
        )

        content, status = _validate_draft(draft, [document], "gemini-answer-test")

        self.assertEqual(status, "partial")
        self.assertFalse(content.evidence[0].verified)
        self.assertFalse(content.calculations[0].matches)
        self.assertGreaterEqual(len(content.gaps), 2)

    def test_reported_key_figure_must_match_its_cited_source(self) -> None:
        document = _document()
        draft = AnswerDraft(
            status="answered",
            answer="INR 999,999 is payable by the due date [E1].",
            key_values=[
                AnswerKeyValueDraft(
                    label="Payable by the due date",
                    value="999999",
                    value_text="INR 999,999",
                    unit="INR",
                    origin="reported",
                    evidence_ids=["E1"],
                )
            ],
            evidence=[
                AnswerEvidenceDraft(
                    id="E1",
                    document_id=document.id,
                    page=1,
                    quote="Payable by 30 May: INR 631,510.",
                )
            ],
        )

        content, status = _validate_draft(draft, [document], "gemini-answer-test")

        self.assertEqual(status, "partial")
        self.assertFalse(content.key_values[0].verified)

    def test_answer_model_setting_is_separate_from_extraction_model(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ANSWER_GENERATION_MODEL": "gemini-answer-test",
                "DOCUMENT_EXTRACTION_MODEL": "gemini-extraction-test",
            },
        ):
            self.assertEqual(answer_model_name(), "gemini-answer-test")

    def test_gemini_schema_omits_unsupported_json_schema_keywords(self) -> None:
        unsupported = {
            "$defs",
            "$ref",
            "anyOf",
            "default",
            "format",
            "maxLength",
            "minLength",
            "pattern",
        }

        def keys(value):
            if isinstance(value, dict):
                yield from value
                for child in value.values():
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keys(child)

        self.assertFalse(unsupported.intersection(keys(gemini_answer_schema())))

    def test_gemini_placeholder_fields_normalize_before_pydantic_validation(self) -> None:
        document = _document()
        draft = _answer_draft_from_gemini(
            {
                "status": "answered",
                "answer": "Payable is INR 631,510 [E1].",
                "key_values": [
                    {
                        "label": "Payable",
                        "value": "631510",
                        "value_text": "INR 631,510",
                        "unit": "INR",
                        "period": "",
                        "origin": "reported",
                        "evidence_ids": ["E1"],
                        "calculation_id": "",
                    }
                ],
                "calculations": [],
                "evidence": [
                    {
                        "id": "E1",
                        "document_id": str(document.id),
                        "page": 1,
                        "sheet": "",
                        "cell_range": "",
                        "quote": "Payable by 30 May: INR 631,510.",
                    }
                ],
                "gaps": [],
            }
        )

        self.assertIsNone(draft.key_values[0].period)
        self.assertIsNone(draft.key_values[0].calculation_id)
        self.assertEqual(draft.evidence[0].page, 1)
        self.assertIsNone(draft.evidence[0].sheet)

    def test_semantic_model_ids_are_remapped_to_citation_ids(self) -> None:
        document = _document()
        draft = _answer_draft_from_gemini(
            {
                "status": "answered",
                "answer": "The readings agree [e_water_prev].",
                "key_values": [
                    {
                        "label": "Calculated consumption",
                        "value": "12500",
                        "value_text": "12,500 kWh",
                        "unit": "kWh",
                        "period": "June 2024",
                        "origin": "calculated",
                        "evidence_ids": ["e_water_prev"],
                        "calculation_id": "calc_water_consumption",
                    }
                ],
                "calculations": [
                    {
                        "id": "calc_water_consumption",
                        "description": "Difference of the meter readings.",
                        "expression": "18450 - 17200",
                        "result": "1250",
                        "unit": "kWh",
                        "evidence_ids": ["e_water_prev"],
                    }
                ],
                "evidence": [
                    {
                        "id": "e_water_prev",
                        "document_id": str(document.id),
                        "page": 1,
                        "sheet": "",
                        "cell_range": "",
                        "quote": "Payable by 30 May: INR 631,510.",
                    }
                ],
                "gaps": [],
            }
        )

        self.assertIn("[E1]", draft.answer)
        self.assertEqual(draft.evidence[0].id, "E1")
        self.assertEqual(draft.calculations[0].id, "C1")
        self.assertEqual(draft.key_values[0].evidence_ids, ["E1"])
        self.assertEqual(draft.key_values[0].calculation_id, "C1")
        self.assertEqual(draft.calculations[0].evidence_ids, ["E1"])

    def test_gemini_answer_uses_answer_model_and_structured_source_context(self) -> None:
        document = _document()
        draft = AnswerDraft(
            status="answered",
            answer="INR 631,510 is payable by the due date [E1].",
            key_values=[],
            evidence=[
                AnswerEvidenceDraft(
                    id="E1",
                    document_id=document.id,
                    page=1,
                    quote="Payable by 30 May: INR 631,510.",
                )
            ],
        )

        class FakeRunnable:
            messages = None

            async def ainvoke(self, messages):
                self.messages = messages
                return {"parsed": draft, "parsing_error": None, "raw": None}

        runnable = FakeRunnable()

        class FakeChatModel:
            options = None

            def __init__(self, **options):
                self.options = options
                FakeChatModel.options = options

            def with_structured_output(self, schema, *, method, include_raw):
                self.schema = schema
                self.method = method
                self.include_raw = include_raw
                return runnable

        with (
            patch.dict(
                "os.environ",
                {
                    "GEMINI_API_KEY": "test-key",
                    "ANSWER_GENERATION_MODEL": "gemini-answer-test",
                    "DOCUMENT_EXTRACTION_MODEL": "gemini-extraction-test",
                },
            ),
            patch("langchain_google_genai.ChatGoogleGenerativeAI", FakeChatModel),
        ):
            content, status = asyncio.run(
                generate_answer("What is payable?", [document])
            )

        self.assertEqual(FakeChatModel.options["model"], "gemini-answer-test")
        self.assertNotIn("temperature", FakeChatModel.options)
        self.assertEqual(status, "answered")
        self.assertTrue(content.evidence[0].verified)
        self.assertIn("631510", runnable.messages[1].content)


if __name__ == "__main__":
    unittest.main()
