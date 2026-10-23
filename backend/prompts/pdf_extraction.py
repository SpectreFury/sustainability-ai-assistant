PDF_SYSTEM_PROMPT = """
Extract source-grounded facts from this PDF. It may be a utility bill, an
operational/waste record, a policy, or a mixed document. Classify it from its
contents, not its filename. Ignore pages that are unrelated inserts.

Return one fact per printed value or distinct policy commitment. Do not calculate,
convert units, estimate, round, or merge different amounts. Preserve every value
exactly in raw_value. Use value_type=numeric only for numeric values, date for
dates, and text for descriptions and commitments. Amounts such as current charges,
amount due, discounted amount, and amount including a late fee are distinct facts;
use specific metric_name values and retain the printed label in dimensions or
description. Record meter readings separately from reported consumption.

For every fact include the physical 1-based PDF page and a short exact quote that
contains the value and enough nearby label text to verify it. Never invent a quote
or cite a page that does not contain the fact. For scanned pages, use visual OCR.
Use ISO dates for event_date and period_start/period_end when the source supports
normalizing them; retain the original date wording in raw_value or source_quote.
Only report an entity name when it appears in the document. Store useful context
such as meter ID, amount label, waste category, destination, scope, or target year
in dimensions.

For bills, capture billing periods, consumption, units, current/previous meter
readings, multiplier, due dates, line-item amounts, taxes, subtotals, and payable
amounts without conflating them. For operational records, extract each dated
quantity and its description/category. For policies, extract scope and explicit
commitments/deadlines as text facts; do not infer a deadline when none is stated.
Do not calculate a financial year or derived totals here; the application handles
those deterministically. Omit unclear facts and add no unsupported values.

Prefer these canonical metric names when applicable: reported_consumption,
current_meter_reading, previous_meter_reading, meter_multiplier, amount_payable,
current_bill_amount, total_bill_amount, amount_payable_by_discount_date,
amount_payable_after_due_date, tax_amount, subtotal, record_quantity,
record_date, and policy_commitment. Keep the exact printed amount label in
dimensions.amount_label; keep meter IDs, waste categories, destinations, and
policy scope in dimensions as well.
""".strip()

PDF_USER_PROMPT = """
Classify this document and extract all useful, well-supported facts using the
requested structured schema. Prefer completeness for relevant facts, but omit
anything that cannot be supported by an exact page and quote. Include separate
facts for reported totals and their components.
""".strip()
