import asyncio
import io
import unittest
from contextlib import nullcontext
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pymupdf
from openpyxl import Workbook

from schemas.documents import DocumentResponse, sanitize_document_error
from schemas.extraction import (
    Extraction,
    ExtractionOut,
    Fact,
    FactOut,
    Locator,
    Segment,
    SourceOut,
)
from services.fact_extraction import _invoke_model, extract_document_facts
from services.fact_persistence import persist_extraction
from services.source_verification import expand_cell_range, verify_fact_source
from services.llm_observability import langfuse_observation
from services.monthly_fact_splitting import split_monthly_column_facts
from services.parsing import ParsedDocument, UnsupportedDocumentError, parse_document
from services.pipeline import get_pipeline


def _pdf_with_pages(*page_texts: str) -> bytes:
    document = pymupdf.open()
    for page_text in page_texts:
        page = document.new_page()
        if page_text:
            page.insert_text((72, 72), page_text)
    data = document.tobytes()
    document.close()
    return data


def _monthly_workbook() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Monthly Summary 2026"
    sheet.append(["Month", "Grid Consumption (kWh)"])
    sheet.append(["January", 100])
    sheet.append(["February", 200])
    sheet.append(["March", 300])
    sheet.append(["ANNUAL TOTAL", 650])
    sheet["B6"] = "=SUM(B2:B4)"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _output_fact(**overrides) -> FactOut:
    values = {
        "key": "units_consumed_kwh_2024_04",
        "label": "Units consumed",
        "category": "consumption",
        "metric": "electricity",
        "series": None,
        "value_text": "47,407 kWh",
        "value_number": 47407.0,
        "unit": "kWh",
        "period_start": "2024-04-01",
        "period_end": "2024-04-30",
        "note": None,
        "source": SourceOut(
            page=1,
            sheet=None,
            cell_range=None,
            quote="Units Consumed: 47,407 kWh",
        ),
    }
    values.update(overrides)
    return FactOut(**values)


class FactExtractionTests(unittest.TestCase):
    def test_pdf_pages_become_segments_and_scans_get_images(self) -> None:
        source = _pdf_with_pages(
            "Units Consumed: 47,407 kWh. Monthly electricity consumption for April 2024.",
            "",
        )
        parsed = parse_document(source, "bill.pdf")

        self.assertEqual(parsed.page_count, 2)
        self.assertEqual(parsed.segments[0].locator.page, 1)
        self.assertIn("Units Consumed", parsed.segments[0].text)
        self.assertFalse(parsed.segments[0].scanned)
        self.assertTrue(parsed.segments[1].scanned)
        self.assertEqual(set(parsed.page_images), {2})

    def test_xlsx_segments_keep_cell_references_values_and_formulas(self) -> None:
        parsed = parse_document(_monthly_workbook(), "annual.xlsx")

        self.assertEqual(len(parsed.segments), 1)
        segment = parsed.segments[0]
        self.assertEqual(segment.locator.sheet, "Monthly Summary 2026")
        self.assertEqual(segment.locator.cell_range, "A1:B6")
        self.assertEqual(segment.cells["B5"], 650.0)
        self.assertIn("B6=", segment.text)
        self.assertIn("(formula =SUM(B2:B4))", segment.text)

    def test_parser_rejects_unsupported_and_corrupt_documents(self) -> None:
        with self.assertRaises(UnsupportedDocumentError):
            parse_document(b"not a document", "notes.txt")
        with self.assertRaises(UnsupportedDocumentError):
            parse_document(b"not a PDF", "broken.pdf")

    def test_page_verification_handles_quotes_values_and_scans(self) -> None:
        segments = parse_document(
            _pdf_with_pages(
                "Units Consumed 47,407 kWh for April. This is the reported monthly electricity usage.",
                "",
            ),
            "bill.pdf",
        ).segments

        self.assertTrue(
            verify_fact_source(segments, Locator(page=1), "Units  Consumed 47,407 kWh", Decimal("47407"))[0]
        )
        self.assertFalse(
            verify_fact_source(segments, Locator(page=1), "Units Consumed 99,999 kWh", Decimal("99999"))[0]
        )
        self.assertFalse(verify_fact_source(segments, Locator(page=3), "anything")[0])
        verified, reason = verify_fact_source(segments, Locator(page=2), "anything")
        self.assertFalse(verified)
        self.assertIn("scanned", reason)

    def test_structured_cell_verification_checks_each_cited_cell(self) -> None:
        segments = parse_document(_monthly_workbook(), "annual.xlsx").segments
        locator = Locator(sheet="Monthly Summary 2026", cell_range="A2:B5")

        self.assertTrue(
            verify_fact_source(
                segments,
                locator,
                "A2=January | B2=100 ... A5=ANNUAL TOTAL | B5=650",
                Decimal("650"),
                structured=True,
            )[0]
        )
        valid, reason = verify_fact_source(
            segments,
            locator,
            "B2=100 | B5=600",
            structured=True,
        )
        self.assertFalse(valid)
        self.assertIn("holds 650", reason)
        self.assertEqual(expand_cell_range("$B$2:B4"), ["B2", "B3", "B4"])

    def test_structured_verification_matches_two_column_pdf_quotes(self) -> None:
        text = (
            "Quality is End-to-End          Food Safety is Everyone's job\n"
            "Quality is embedded across the  Each of us plays a vital role\n"
            "entire value chain, from ideation  in delivering our promise\n"
        )
        segments = [Segment(ordinal=0, locator=Locator(page=1), text=text)]
        quote = "Quality is embedded across the\nentire value chain, from ideation"

        self.assertFalse(verify_fact_source(segments, Locator(page=1), quote)[0])
        self.assertTrue(verify_fact_source(segments, Locator(page=1), quote, structured=True)[0])

    def test_listed_monthly_column_is_split_into_verified_cell_facts(self) -> None:
        segments = parse_document(_monthly_workbook(), "annual.xlsx").segments
        listed = Fact(
            key="monthly_grid_consumption",
            label="Grid consumption",
            category="consumption",
            metric="electricity",
            series="Grid consumption (kWh)",
            value_text="January 100; February 200; March 300",
            value_number=None,
            unit="kWh",
            period_start="2026-01-01",
            period_end="2026-12-31",
            locator=Locator(sheet="Monthly Summary 2026", cell_range="B2:B4"),
            quote="January 100; February 200; March 300",
        )

        split = split_monthly_column_facts([listed], segments)
        self.assertEqual(
            [(fact.value_number, fact.period_start, fact.period_end) for fact in split],
            [
                (Decimal("100.0"), "2026-01-01", "2026-01-31"),
                (Decimal("200.0"), "2026-02-01", "2026-02-28"),
                (Decimal("300.0"), "2026-03-01", "2026-03-31"),
            ],
        )
        self.assertTrue(all(fact.verified for fact in split))
        self.assertEqual([fact.locator.cell_range for fact in split], ["B2", "B3", "B4"])

    def test_model_facts_are_structured_verified_and_calculations_separate(self) -> None:
        source = _pdf_with_pages(
            "Units Consumed: 47,407 kWh. Monthly electricity consumption for April 2024."
        )
        output = ExtractionOut(
            doc_type="electricity_bill",
            title="Electricity bill",
            organisation="Example Factory",
            issuer="Example Power",
            period_start="2024-04-01",
            period_end="2024-04-30",
            summary="April electricity bill.",
            facts=[_output_fact()],
            issues=[],
        )

        with patch(
            "services.fact_extraction._invoke_model",
            new=AsyncMock(return_value=output),
        ):
            extracted = asyncio.run(extract_document_facts("bill.pdf", source))

        self.assertEqual(extracted.doc_type, "electricity_bill")
        self.assertEqual(extracted.organisation, "Example Factory")
        self.assertEqual(len(extracted.facts), 2)
        reported, calculated = extracted.facts
        self.assertTrue(reported.verified)
        self.assertEqual(reported.value_number, Decimal("47407.0"))
        self.assertEqual(reported.locator.page, 1)
        self.assertEqual(calculated.origin, "calculated")
        self.assertEqual(calculated.value_number, Decimal("1580.2333"))
        self.assertIn("÷ 30 days", calculated.derivation)

    def test_gemini_structured_model_call_uses_segment_context(self) -> None:
        output = ExtractionOut(
            doc_type="other",
            title="Test document",
            organisation=None,
            issuer=None,
            period_start=None,
            period_end=None,
            summary="A source-grounded test document.",
            facts=[_output_fact()],
            issues=[],
        )

        class FakeRaw:
            usage_metadata = {
                "input_tokens": 20,
                "output_tokens": 10,
                "total_tokens": 30,
            }

        class FakeRunnable:
            messages = None

            async def ainvoke(self, messages):
                self.messages = messages
                return {"parsed": output, "parsing_error": None, "raw": FakeRaw()}

        runnable = FakeRunnable()

        class FakeChatModel:
            options = None

            def __init__(self, **options):
                self.options = options
                FakeChatModel.options = options

            def with_structured_output(self, schema, *, include_raw):
                self.schema = schema
                self.include_raw = include_raw
                return runnable

        parsed = ParsedDocument(
            filename="bill.pdf",
            kind="pdf",
            page_count=1,
            segments=[
                Segment(
                    ordinal=0,
                    locator=Locator(page=1),
                    text="Units Consumed: 47,407 kWh. Monthly electricity use for April 2024.",
                )
            ],
        )
        with (
            patch.dict(
                "os.environ",
                {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "gemini-test"},
            ),
            patch("langchain_google_genai.ChatGoogleGenerativeAI", FakeChatModel),
            patch(
                "services.fact_extraction.langfuse_observation",
                side_effect=lambda **_kwargs: nullcontext(None),
            ),
        ):
            extracted = asyncio.run(
                _invoke_model(b"pdf bytes", parsed, get_pipeline("improved"), None)
            )

        self.assertEqual(extracted.doc_type, "other")
        self.assertEqual(FakeChatModel.options["model"], "gemini-test")
        self.assertEqual(FakeChatModel.options["temperature"], 0)
        self.assertTrue(runnable.messages)
        self.assertIn("meticulous sustainability data analyst", runnable.messages[0].content)
        self.assertIn("Units Consumed", runnable.messages[1].content[1]["text"])

    def test_persistence_sanitizes_text_and_stores_segments_with_facts(self) -> None:
        class RecordingSession:
            def __init__(self):
                self.rows = []

            def add_all(self, rows):
                self.rows.extend(rows)

        extracted = Extraction(
            doc_type="other",
            title="Test document",
            summary="Test.",
            facts=[
                Fact(
                    key="reported_quantity\x00",
                    label="Units\x00 consumed",
                    category="quantity",
                    value_text="2\x00321 units",
                    value_number=Decimal("2321"),
                    locator=Locator(page=1),
                    quote="Units\x00 consumed: 2,321",
                    verified=True,
                    verification="Quote found on p.1",
                )
            ],
            issues=[],
            segments=[
                Segment(
                    ordinal=0,
                    locator=Locator(page=1),
                    text="Units\x00 consumed: 2,321",
                )
            ],
            model="gemini-test",
            pipeline="improved",
        )
        session = RecordingSession()

        asyncio.run(
            persist_extraction(
                session,
                document_id=uuid4(),
                run=SimpleNamespace(id=uuid4()),
                extracted=extracted,
            )
        )

        self.assertEqual(len(session.rows), 2)
        segment, fact = session.rows
        self.assertNotIn("\x00", fact.key)
        self.assertNotIn("\x00", fact.quote)
        self.assertNotIn("\x00", segment.text)
        self.assertEqual(fact.value_number, Decimal("2321"))
        self.assertEqual(segment.locator, {"page": 1})

    def test_internal_database_errors_are_not_user_facing(self) -> None:
        internal = "sqlalchemy.exc.IntegrityError: INSERT INTO facts"
        self.assertEqual(
            sanitize_document_error(internal),
            "Document processing failed. Please try again or contact support.",
        )
        response = DocumentResponse(
            id=uuid4(),
            user_id=1,
            filename="bill.pdf",
            cloudinary_url=None,
            cloudinary_public_id="documents/1/bill.pdf",
            status="failed",
            error_message=internal,
            upload_timestamp=datetime.now(UTC),
        )
        self.assertEqual(
            response.error_message,
            "Document processing failed. Please try again or contact support.",
        )

    def test_langfuse_observation_remains_optional(self) -> None:
        class FakeObservation:
            def __init__(self):
                self.updates = []

            def update(self, **values):
                self.updates.append(values)

        class FakeContext:
            def __init__(self, observation):
                self.observation = observation

            def __enter__(self):
                return self.observation

            def __exit__(self, *_args):
                return False

        class FakeClient:
            def __init__(self):
                self.attributes = None
                self.observation = FakeObservation()

            def start_as_current_observation(self, **attributes):
                self.attributes = attributes
                return FakeContext(self.observation)

        client = FakeClient()
        with patch("services.llm_observability.get_langfuse_client", return_value=client):
            with langfuse_observation(
                as_type="generation",
                name="test-generation",
                model="gemini-test",
            ) as observation:
                observation.update(output={"fact_count": 1})

        self.assertEqual(client.attributes["name"], "test-generation")
        self.assertEqual(client.observation.updates, [{"output": {"fact_count": 1}}])


if __name__ == "__main__":
    unittest.main()
