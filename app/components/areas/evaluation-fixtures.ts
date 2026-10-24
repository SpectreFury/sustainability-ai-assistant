export type EvaluationChecks = [boolean, boolean, boolean, boolean]

export type EvaluationCase = {
  id: string
  title: string
  question: string
  context: string
  domain: string
  expected: string
  baselineAnswer: string
  improvedAnswer: string
  baselineChecks: EvaluationChecks
  improvedChecks: EvaluationChecks
  baselineFailure: string
  improvement: string
  limitations: string
  evidence: { label: string; value: string }[]
}

export const evaluationCases: EvaluationCase[] = [
  {
    id: "E01",
    title: "Payable amount is not current charges",
    question: "What is the total amount payable for June, including arrears?",
    context: "BESCOM Commercial Electricity Bill.pdf · p.1 · Charges summary",
    domain: "Finance interpretation · Electricity bill · INR",
    expected:
      "Return ₹120,000 as total payable. Distinguish ₹112,500 in current charges from ₹7,500 in arrears, and cite the payment summary.",
    baselineAnswer: "The total payable is ₹112,500.",
    improvedAnswer:
      "The bill reports ₹112,500 in current charges plus ₹7,500 in arrears: ₹112,500 + ₹7,500 = ₹120,000. This is the source-reported total payable. [1]",
    baselineChecks: [false, true, false, true],
    improvedChecks: [true, true, true, true],
    baselineFailure:
      "The answer cites the right page but selects current charges instead of total payable, understating the amount by ₹7,500.",
    improvement:
      "The answer preserves current charges, arrears, and total payable as separate values, then checks their relationship.",
    limitations:
      "The example values and source location have not been checked against the original bill.",
    evidence: [
      { label: "Current charges", value: "₹112,500" },
      { label: "Arrears", value: "₹7,500" },
      { label: "Total payable", value: "₹120,000" },
    ],
  },
  {
    id: "E02",
    title: "Current-period charges only",
    question: "What are the current-period electricity charges, excluding arrears?",
    context: "BESCOM Commercial Electricity Bill.pdf · p.1 · Charges summary",
    domain: "Finance interpretation · Electricity bill · INR",
    expected:
      "Return ₹112,500 as current-period charges and keep the ₹7,500 arrears separate.",
    baselineAnswer: "The current charges are ₹120,000.",
    improvedAnswer:
      "Current-period charges are ₹112,500. The bill lists ₹7,500 separately as arrears. [1]",
    baselineChecks: [false, true, false, true],
    improvedChecks: [true, true, true, true],
    baselineFailure:
      "The answer combines arrears with charges for the current billing period.",
    improvement:
      "The improved answer reports the named charge field and keeps arrears separate.",
    limitations: "Illustrative amount semantics; verify against the bill before promotion.",
    evidence: [
      { label: "Current charges", value: "₹112,500" },
      { label: "Arrears excluded", value: "₹7,500" },
    ],
  },
  {
    id: "E03",
    title: "Meter multiplier and consumption",
    question: "What electricity consumption does the meter report for June?",
    context: "BESCOM Commercial Electricity Bill.pdf · p.1 · Meter table",
    domain: "Meter reconciliation · Electricity · kWh",
    expected:
      "Report 12,500 kWh and show that (18,450 − 17,200) × 10 = 12,500 kWh.",
    baselineAnswer:
      "The June reading difference is 1,250 and the multiplier is 10, giving 12,500 kWh. [1]",
    improvedAnswer:
      "The bill reports 12,500 kWh for June. The readings and multiplier reconcile: (18,450 − 17,200) × 10 = 12,500 kWh. [1] [C1]",
    baselineChecks: [true, true, true, true],
    improvedChecks: [true, true, true, true],
    baselineFailure: "No failure recorded in this illustrative case.",
    improvement:
      "The answer keeps the reported consumption distinct from the arithmetic check.",
    limitations: "Illustrative readings and multiplier; verify against the original meter table.",
    evidence: [
      { label: "Previous reading", value: "17,200" },
      { label: "Current reading", value: "18,450" },
      { label: "Multiplier", value: "10" },
      { label: "Reported consumption", value: "12,500 kWh" },
    ],
  },
  {
    id: "E04",
    title: "Water meter reconciliation",
    question: "Does billed water consumption match the meter readings?",
    context: "Water invoice.pdf · p.1 · Meter and volume",
    domain: "Meter reconciliation · Water · m³",
    expected:
      "Keep the billed 185 m³ separate from the 180 m³ meter difference and state the 5 m³ discrepancy.",
    baselineAnswer: "The meter readings show 180 m³ of water consumption.",
    improvedAnswer:
      "The invoice bills 185 m³. The readings differ by 180 m³ (1,260 − 1,080), leaving a 5 m³ discrepancy. [1] [C1]",
    baselineChecks: [false, true, false, false],
    improvedChecks: [true, true, true, true],
    baselineFailure:
      "The answer omits the billed volume and does not identify the discrepancy.",
    improvement:
      "The billed value and meter-derived value are reported separately; the difference is calculated explicitly.",
    limitations: "Illustrative invoice figures; verify the billed and meter values against the source.",
    evidence: [
      { label: "Billed volume", value: "185 m³" },
      { label: "Meter readings", value: "1,080 → 1,260" },
      { label: "Meter difference", value: "180 m³" },
    ],
  },
  {
    id: "E05",
    title: "Total recorded waste: no data",
    question: "What total waste quantity is recorded?",
    context: "Waste form · Processing",
    domain: "Evidence availability · Waste",
    expected:
      "Say there are no usable waste records and do not convert missing records into zero.",
    baselineAnswer: "No usable waste quantity is recorded in the selected source.",
    improvedAnswer: "No usable waste records are available, so no total can be established.",
    baselineChecks: [true, true, true, true],
    improvedChecks: [true, true, true, true],
    baselineFailure: "No failure recorded in this illustrative case.",
    improvement: "Both versions distinguish missing data from zero waste.",
    limitations: "The pictured waste form is still processing; no original values are verified.",
    evidence: [{ label: "Usable records", value: "None shown" }],
  },
  {
    id: "E06",
    title: "Monthly versus annual agreement",
    question: "Do the workbook’s monthly values and annual summary agree?",
    context: "Annual Electricity Consumption.xlsx · C2:C4 and C14",
    domain: "Workbook reconciliation · Electricity · kWh",
    expected:
      "Report the monthly sum of 38,000 kWh, compare it with the reported 50,000 kWh annual cell, and state the 12,000 kWh discrepancy.",
    baselineAnswer: "The annual total is 50,000 kWh.",
    improvedAnswer:
      "The three recorded monthly values sum to 38,000 kWh, while the annual cell reports 50,000 kWh. They differ by 12,000 kWh; the missing months are not treated as zero. [1] [C1]",
    baselineChecks: [false, true, false, true],
    improvedChecks: [true, true, true, true],
    baselineFailure:
      "The answer repeats the annual summary without checking it against the recorded monthly values.",
    improvement:
      "The answer compares source-reported and calculated values and calls out incomplete monthly coverage.",
    limitations: "Illustrative workbook cells and figures; verify sheet names and values in the source file.",
    evidence: [
      { label: "Recorded months", value: "12,000 · 13,500 · 12,500 kWh" },
      { label: "Calculated sum", value: "38,000 kWh" },
      { label: "Reported annual cell", value: "50,000 kWh" },
    ],
  },
  {
    id: "E07",
    title: "Avoid overlapping bill double count",
    question: "Should the bill’s June consumption be added to the workbook total?",
    context: "Workbook C4 + BESCOM p.1",
    domain: "Source selection · Electricity · kWh",
    expected:
      "Treat the bill as corroboration when its June value matches the workbook cell; do not add it twice.",
    baselineAnswer:
      "The workbook and bill both report June consumption of 12,500 kWh; count it once.",
    improvedAnswer:
      "The bill corroborates the workbook’s June value of 12,500 kWh. It is not added a second time. [1]",
    baselineChecks: [true, true, true, true],
    improvedChecks: [true, true, true, true],
    baselineFailure: "No failure recorded in this illustrative case.",
    improvement: "The source treatment is explicit and avoids double counting.",
    limitations: "Illustrative cross-document match; original workbook and bill not verified here.",
    evidence: [
      { label: "Workbook June value", value: "12,500 kWh" },
      { label: "Bill June value", value: "12,500 kWh" },
      { label: "Treatment", value: "Corroboration only" },
    ],
  },
  {
    id: "E08",
    title: "Indian FY date boundaries",
    question: "What dates define FY 2025–26?",
    context: "Indian financial year · 01 Apr 2025–31 Mar 2026",
    domain: "Financial year · India",
    expected: "Use 1 April 2025 through 31 March 2026 as the financial-year window.",
    baselineAnswer: "FY 2025–26 runs from 1 April 2025 to 31 March 2026.",
    improvedAnswer: "FY 2025–26 covers 1 April 2025 through 31 March 2026.",
    baselineChecks: [true, true, true, true],
    improvedChecks: [true, true, true, true],
    baselineFailure: "No failure recorded in this illustrative case.",
    improvement: "Both versions use the Indian April–March boundary.",
    limitations: "A boundary check only; it does not prove source completeness within the year.",
    evidence: [
      { label: "Start date", value: "2025-04-01" },
      { label: "End date", value: "2026-03-31" },
    ],
  },
  {
    id: "E09",
    title: "Unknown policy complaint deadline",
    question: "Does the policy specify a deadline for resolving customer complaints?",
    context: "Quality policy · Deadline not established",
    domain: "Policy interpretation · Customer complaints",
    expected:
      "State that no complaint-resolution deadline is established by the supplied policy evidence.",
    baselineAnswer: "The selected policy does not establish a complaint-resolution deadline.",
    improvedAnswer: "Customer complaints are resolved within 30 days.",
    baselineChecks: [true, true, true, true],
    improvedChecks: [false, true, true, false],
    baselineFailure: "The baseline correctly states that the deadline is not established.",
    improvement:
      "This illustrative improved answer regresses by asserting a deadline without supporting evidence.",
    limitations:
      "The policy extraction is shown as failed; no deadline or policy wording is verified.",
    evidence: [{ label: "Deadline evidence", value: "No verified excerpt" }],
  },
  {
    id: "E10",
    title: "Keep different organizations apart",
    question: "Which electricity records belong to the Bengaluru facility?",
    context: "Adani p.1 + BESCOM p.1 · Separate facilities",
    domain: "Entity scope · Electricity",
    expected:
      "Keep the Ahmedabad Adani bill separate from the Bengaluru BESCOM facility records.",
    baselineAnswer: "The records include electricity use from both facilities.",
    improvedAnswer: "The selected total combines Adani and BESCOM electricity records.",
    baselineChecks: [false, true, false, false],
    improvedChecks: [false, true, true, false],
    baselineFailure: "The answer blends values from separate organizations.",
    improvement:
      "Entity isolation remains unresolved in this illustrative comparison.",
    limitations:
      "Organization labels and source references require verification against the original bills.",
    evidence: [
      { label: "Bengaluru facility", value: "BESCOM" },
      { label: "Separate facility", value: "Adani · Ahmedabad" },
    ],
  },
]

export const evaluationDimensions = [
  { key: "answer", label: "Answer" },
  { key: "evidence", label: "Evidence" },
  { key: "calculation", label: "Calculation" },
  { key: "uncertainty", label: "Uncertainty" },
] as const

export function allDimensionsPass(checks: EvaluationChecks) {
  return checks.every(Boolean)
}

export function passedChecks(checks: EvaluationChecks) {
  return checks.filter(Boolean).length
}
