"""KuKi's first source-grounded evaluation pack.

The cases below were authored against kuki-assignment-dataset and are
independent from the /benchmark evaluation pack. Expected locators identify the
source cells/pages used for deterministic evidence scoring.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

CASE_SET_VERSION = "kuki-dataset-v1"

EVALUATION_CASES: list[dict[str, Any]] = [
    {
        "id": "EV01",
        "title": "June electricity series",
        "question": (
            "In Monthly Summary 2026, what values are reported for June for "
            "Grid Supply, Solar Power, Wind Power, Total Renewable, and Total "
            "Consumption? Give each value as reported with its unit."
        ),
        "domain": "Workbook extraction · Electricity · kWh",
        "required_documents": ["Annual Electricity Consumption.xlsx"],
        "expected_status": "answered",
        "expected_numeric_values": [
            {"value": "127800", "unit": "kWh"},
            {"value": "72800", "unit": "kWh"},
            {"value": "8900", "unit": "kWh"},
            {"value": "81700", "unit": "kWh"},
            {"value": "209500", "unit": "kWh"},
        ],
        "expected_value_assertions": [
            {
                "filename": "Annual Electricity Consumption.xlsx",
                "value": value,
                "unit": "kWh",
                "label_terms": label_terms,
                "sheet": "Monthly Summary 2026",
                "cell": cell,
                "period_start": "2026-06-01",
                "period_end": "2026-06-30",
            }
            for value, label_terms, cell in [
                ("127800", ["grid supply"], "B8"),
                ("72800", ["solar power"], "C8"),
                ("8900", ["wind power"], "D8"),
                ("81700", ["total renewable"], "E8"),
                ("209500", ["total consumption"], "F8"),
            ]
        ],
        "expected_term_groups": [["june", "2026-06"]],
        "expected_evidence": [
            {"filename": "Annual Electricity Consumption.xlsx", "sheet": "Monthly Summary 2026", "cell": cell}
            for cell in ["B8", "C8", "D8", "E8", "F8"]
        ],
        "calculation": None,
        "uncertainty_terms": [],
    },
    {
        "id": "EV02",
        "title": "Quarterly consumption and renewable share",
        "question": "What total consumption and renewable percentage does the Quarterly Summary report for Q2?",
        "domain": "Workbook extraction · Quarterly summary",
        "required_documents": ["Annual Electricity Consumption.xlsx"],
        "expected_status": "answered",
        "expected_numeric_values": [
            {"value": "628300", "unit": "kWh"},
            {"value": "38.9", "unit": "%"},
        ],
        "expected_value_assertions": [
            {
                "filename": "Annual Electricity Consumption.xlsx",
                "value": "628300",
                "unit": "kWh",
                "label_terms": ["total consumption"],
                "sheet": "Quarterly Summary",
                "cell": "G3",
            },
            {
                "filename": "Annual Electricity Consumption.xlsx",
                "value": "38.9",
                "unit": "%",
                "label_terms": ["renewable"],
                "sheet": "Quarterly Summary",
                "cell": "H3",
            },
        ],
        "expected_term_groups": [["Q2"]],
        "expected_evidence": [
            {"filename": "Annual Electricity Consumption.xlsx", "sheet": "Quarterly Summary", "cell": "G3"},
            {"filename": "Annual Electricity Consumption.xlsx", "sheet": "Quarterly Summary", "cell": "H3"},
        ],
        "calculation": None,
        "uncertainty_terms": [],
    },
    {
        "id": "EV03",
        "title": "Renewable generation and avoided emissions",
        "question": (
            "In Source-wise Annual Analysis, what annual generation and CO2 "
            "avoided amounts are reported for Solar Power and Wind Power? "
            "Keep kg and tonnes as separate units."
        ),
        "domain": "Workbook extraction · Electricity · Emissions",
        "required_documents": ["Annual Electricity Consumption.xlsx"],
        "expected_status": "answered",
        "expected_numeric_values": [
            {"value": "771065", "unit": "kWh"},
            {"value": "616852", "unit": "kg"},
            {"value": "616.9", "unit": "tonnes"},
            {"value": "120768", "unit": "kWh"},
            {"value": "96614", "unit": "kg"},
            {"value": "96.6", "unit": "tonnes"},
        ],
        "expected_value_assertions": [
            {
                "filename": "Annual Electricity Consumption.xlsx",
                "value": value,
                "unit": unit,
                "label_terms": label_terms,
                "sheet": "Source-wise Annual Analysis",
                "cell": cell,
            }
            for value, unit, label_terms, cell in [
                ("771065", "kWh", ["solar power", "generation"], "B3"),
                ("616852", "kg", ["solar power", "co2 avoided"], "G3"),
                ("616.9", "tonnes", ["solar power", "co2 avoided"], "H3"),
                ("120768", "kWh", ["wind power", "generation"], "B4"),
                ("96614", "kg", ["wind power", "co2 avoided"], "G4"),
                ("96.6", "tonnes", ["wind power", "co2 avoided"], "H4"),
            ]
        ],
        "expected_term_groups": [["solar power", "solar"], ["wind power", "wind"]],
        "expected_evidence": [
            {"filename": "Annual Electricity Consumption.xlsx", "sheet": "Source-wise Annual Analysis", "cell": cell}
            for cell in ["B3", "G3", "H3", "B4", "G4", "H4"]
        ],
        "calculation": None,
        "uncertainty_terms": [],
    },
    {
        "id": "EV04",
        "title": "Grid emissions are not numeric",
        "question": (
            "Does Source-wise Annual Analysis give a numeric CO2 avoided "
            "amount for Grid Electricity? Report what the cells show; do not "
            "treat a dash as zero."
        ),
        "domain": "Missing-value handling · Emissions",
        "required_documents": ["Annual Electricity Consumption.xlsx"],
        "expected_status": "answered",
        "expected_numeric_values": [],
        "expected_term_groups": [
            [
                "dash",
                "dashes",
                "not reported",
                "not numeric",
                "no numeric",
                "not provided",
                "no value",
                "does not give a numeric",
                "does not provide a numeric",
            ]
        ],
        "expected_evidence": [
            {"filename": "Annual Electricity Consumption.xlsx", "sheet": "Source-wise Annual Analysis", "cell": "G2"},
            {"filename": "Annual Electricity Consumption.xlsx", "sheet": "Source-wise Annual Analysis", "cell": "H2"},
        ],
        "forbidden_numeric_values": ["0"],
        "calculation": None,
        "uncertainty_terms": [],
    },
    {
        "id": "EV05",
        "title": "Waste entries remain separate records",
        "question": (
            "List the waste entries on the form with each waste description, "
            "quantity, and destination. Keep the entries separate and do not total them."
        ),
        "domain": "Record extraction · Waste",
        "required_documents": ["form 3 filled.docx.pdf"],
        "expected_status": "answered",
        "expected_numeric_values": [],
        "expected_value_assertions": [
            {
                "filename": "form 3 filled.docx.pdf",
                "value": value,
                "unit": "T",
                "label_terms": [label],
                "source_terms": destination_terms,
                "page": 1,
            }
            for value, label, destination_terms in [
                ("1.0", "ETP sludge", ["TNWML", "Gummidipoondi"]),
                ("0.5", "Waste Powder", ["Quality Business Systems"]),
                ("0.5", "Phosphate Sludge", ["TNWML", "Gummidipoondi"]),
                ("0.4", "residues containing oil", ["Quality Business Systems"]),
            ]
        ],
        "expected_term_groups": [
            ["ETP sludge"], ["1.0 T", "1 T"], ["TNWML"], ["Gummidipoondi"],
            ["Waste Powder"], ["Quality Business Systems"],
            ["Phosphate Sludge"], ["residues containing oil"], ["0.4 T"],
        ],
        "expected_term_occurrences": [{"term": "0.5 T", "count": 2}],
        "expected_evidence": [
            {"filename": "form 3 filled.docx.pdf", "page": 1},
        ],
        "calculation": None,
        "uncertainty_terms": [],
    },
    {
        "id": "EV06",
        "title": "Policy ownership metadata",
        "question": (
            "What issuing department, target audience, approver, and approval "
            "date are stated in the Food Safety and Quality Policy?"
        ),
        "domain": "Policy extraction · Governance",
        "required_documents": ["quality_policy_nestle.pdf"],
        "expected_status": "answered",
        "expected_numeric_values": [],
        "expected_term_groups": [
            ["Corporate Quality Management"],
            ["All employees"],
            ["Executive Board"],
            ["June 2026"],
        ],
        "expected_evidence": [
            {"filename": "quality_policy_nestle.pdf", "page": 2},
        ],
        "calculation": None,
        "uncertainty_terms": [],
    },
    {
        "id": "EV07",
        "title": "Approval date is not an effective date",
        "question": (
            "Does the Food Safety and Quality Policy state an effective date "
            "separate from its approval date? If no separate effective date is "
            "shown, say so and cite the approval-date entry without treating it "
            "as an effective date."
        ),
        "domain": "Uncertainty handling · Policy dates",
        "required_documents": ["quality_policy_nestle.pdf"],
        "expected_status": "insufficient_evidence",
        "expected_numeric_values": [],
        "expected_term_groups": [],
        "expected_evidence": [
            {
                "filename": "quality_policy_nestle.pdf",
                "page": 2,
                "quote_terms": ["Date of approval", "June 2026"],
            },
        ],
        "calculation": None,
        "uncertainty_terms": [
            [
                "effective date is not stated",
                "does not state an effective date",
                "do not state an effective date",
                "does not give an effective date",
                "no effective date",
                "approval date only",
            ]
        ],
        "expected_extraction_absent_terms": ["effective date"],
    },
    {
        "id": "EV08",
        "title": "Water invoice dates and payable status",
        "question": (
            "What invoice date, billing period, due date, total amount due, and "
            "payment status does water_bill_invoice.pdf state?"
        ),
        "domain": "Bill extraction · Water · INR",
        "required_documents": ["water_bill_invoice.pdf"],
        "expected_status": "answered",
        "expected_numeric_values": [{"value": "158733.62", "unit": "INR"}],
        "expected_term_groups": [
            ["31st December 2025", "31 December 2025", "2025-12-31"],
            ["01st December 2025", "1 December 2025", "2025-12-01"],
            ["15th January 2026", "15 January 2026", "2026-01-15"],
            ["PENDING", "pending"],
        ],
        "expected_evidence": [
            {"filename": "water_bill_invoice.pdf", "page": 1},
            {"filename": "water_bill_invoice.pdf", "page": 2},
        ],
        "calculation": None,
        "uncertainty_terms": [],
    },
    {
        "id": "EV09",
        "title": "Water surcharge line item",
        "question": (
            "What rate, quantity, and amount does the water invoice report for "
            "the Water Quality Surcharge? Include the billing period."
        ),
        "domain": "Bill line item · Water · INR",
        "required_documents": ["water_bill_invoice.pdf"],
        "expected_status": "answered",
        "expected_numeric_values": [
            {"value": "5.00", "unit": "INR/Cu.M"},
            {"value": "2321", "unit": "Cu.M"},
            {"value": "11605.00", "unit": "INR"},
        ],
        "expected_term_groups": [["Water Quality Surcharge"], ["December 2025", "2025-12"]],
        "expected_evidence": [
            {"filename": "water_bill_invoice.pdf", "page": 1},
        ],
        "calculation": None,
        "uncertainty_terms": [],
    },
    {
        "id": "EV10",
        "title": "June renewable total arithmetic",
        "question": (
            "For June in Monthly Summary 2026, does the reported Total "
            "Renewable equal Solar Power plus Wind Power? Show the calculation."
        ),
        "domain": "Calculation verification · Electricity · kWh",
        "required_documents": ["Annual Electricity Consumption.xlsx"],
        "expected_status": "answered",
        "expected_numeric_values": [{"value": "81700", "unit": "kWh"}],
        "expected_term_groups": [],
        "expected_evidence": [
            {"filename": "Annual Electricity Consumption.xlsx", "sheet": "Monthly Summary 2026", "cell": cell}
            for cell in ["C8", "D8", "E8"]
        ],
        "calculation": {
            "result": "81700",
            "unit": "kWh",
            "operands": ["72800", "8900"],
            "operator": "+",
            "expected_evidence": [
                {"filename": "Annual Electricity Consumption.xlsx", "sheet": "Monthly Summary 2026", "cell": "C8"},
                {"filename": "Annual Electricity Consumption.xlsx", "sheet": "Monthly Summary 2026", "cell": "D8"},
            ],
        },
        "expected_value_assertions": [
            {
                "filename": "Annual Electricity Consumption.xlsx",
                "value": "81700",
                "unit": "kWh",
                "label_terms": ["total renewable"],
                "sheet": "Monthly Summary 2026",
                "cell": "E8",
            }
        ],
        "uncertainty_terms": [],
    },
    {
        "id": "EV11",
        "title": "Financial-year resource coverage and no-data handling",
        "question": (
            "Using only Annual Electricity Consumption.xlsx, what does the "
            "Financial-Year Summary show for electricity, water, and waste in "
            "FY 2026-27? State the electricity period coverage and whether the "
            "other resources have usable records."
        ),
        "domain": "Financial-year summary · Electricity · Coverage",
        "runner": "financial_year_summary",
        "required_documents": ["Annual Electricity Consumption.xlsx"],
        "expected_status": "partial",
        "expected_value_assertions": [
            {
                "filename": "Annual Electricity Consumption.xlsx",
                "value": value,
                "unit": "kWh",
                "label_terms": ["total consumption"],
                "sheet": "Monthly Summary 2026",
                "cell": cell,
                "period_start": period_start,
                "period_end": period_end,
            }
            for value, cell, period_start, period_end in [
                ("203900", "F6", "2026-04-01", "2026-04-30"),
                ("214900", "F7", "2026-05-01", "2026-05-31"),
                ("209500", "F8", "2026-06-01", "2026-06-30"),
                ("194100", "F9", "2026-07-01", "2026-07-31"),
                ("198600", "F10", "2026-08-01", "2026-08-31"),
                ("206300", "F11", "2026-09-01", "2026-09-30"),
                ("211600", "F12", "2026-10-01", "2026-10-31"),
                ("203500", "F13", "2026-11-01", "2026-11-30"),
                ("199400", "F14", "2026-12-01", "2026-12-31"),
            ]
        ],
        "expected_evidence": [
            {
                "filename": "Annual Electricity Consumption.xlsx",
                "sheet": "Monthly Summary 2026",
                "cell": f"F{row}",
            }
            for row in range(6, 15)
        ],
        "financial_year_expected": {
            "financial_year": "2026-27",
            "metric": "electricity",
            "series_terms": ["total consumption"],
            "value": "1841800",
            "unit": "kWh",
            "months_covered": 9,
            "covered_months": ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
            "missing_months": ["Jan", "Feb", "Mar"],
            "no_data_metrics": ["water", "waste"],
        },
    },
]


def case_set_hash() -> str:
    encoded = json.dumps(EVALUATION_CASES, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def public_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": case["id"],
        "title": case["title"],
        "question": case["question"],
        "domain": case["domain"],
        "runner": case.get("runner", "answer"),
        "required_documents": case["required_documents"],
        "expected_status": case["expected_status"],
        "expected_evidence": case["expected_evidence"],
    }
