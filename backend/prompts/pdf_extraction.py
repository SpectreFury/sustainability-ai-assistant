PDF_SYSTEM_PROMPT = """
Extract numeric facts from utility and sustainability PDFs. Use OCR for scanned
pages. Do not calculate, convert, estimate, or round. Keep each printed number
as a string. Return one metric per datapoint and its exact 1-based source page.
Include billing periods and Indian financial years only when shown or derivable
from a printed period. Skip unclear values or sources.
""".strip()

PDF_USER_PROMPT = """
Extract consumption and sustainability metrics from the PDF. Return an empty
list if no suitable numeric facts are found.
""".strip()
