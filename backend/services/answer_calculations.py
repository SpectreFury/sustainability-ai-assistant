"""Evaluate model-proposed arithmetic without executing arbitrary Python."""

import ast
import operator
import re
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_HALF_UP

from schemas.extraction import Segment
from services.source_verification import expand_cell_range, parse_cell_number

_SHEET_RANGE = re.compile(
    r"(?:'([^']+)'|([A-Za-z_][\w .&()-]*?))!"
    r"(\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)",
    re.IGNORECASE,
)
_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


class CalculationError(ValueError):
    """The expression is not in the supported, safe arithmetic subset."""


def _flatten(values: list[Decimal | list[Decimal]]) -> list[Decimal]:
    flattened: list[Decimal] = []
    for value in values:
        flattened.extend(value if isinstance(value, list) else [value])
    return flattened


def _round(value: Decimal, digits: Decimal = Decimal(0)) -> Decimal:
    if digits != digits.to_integral_value() or abs(digits) > 12:
        raise CalculationError("ROUND precision must be an integer from -12 to 12")
    quantum = Decimal(1).scaleb(-int(digits))
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


_FUNCTIONS = {
    "SUM": lambda *values: sum(_flatten(list(values)), Decimal(0)),
    "AVERAGE": lambda *values: sum(_flatten(list(values)), Decimal(0))
    / len(_flatten(list(values))),
    "MIN": lambda *values: min(_flatten(list(values))),
    "MAX": lambda *values: max(_flatten(list(values))),
    "ABS": abs,
    "ROUND": _round,
}


def _decimal_cell_values(
    segments: list[Segment], sheet: str, cell_range: str
) -> list[Decimal]:
    references = expand_cell_range(cell_range)
    if not references or len(references) > 5000:
        raise CalculationError(f"Invalid or oversized cell range: {sheet}!{cell_range}")

    cells: dict[str, float | str] = {}
    for segment in segments:
        if (
            segment.locator.sheet
            and segment.locator.sheet.casefold() == sheet.casefold()
            and segment.cells
        ):
            cells.update({reference.upper(): value for reference, value in segment.cells.items()})

    values: list[Decimal] = []
    for reference in references:
        if reference.upper() not in cells:
            continue
        number = parse_cell_number(cells[reference.upper()])
        if number is not None:
            values.append(number)
        elif ":" not in cell_range:
            raise CalculationError(f"{sheet}!{reference} is not numeric")
    if not values:
        raise CalculationError(f"No numeric cells at {sheet}!{cell_range}")
    return values


def evaluate_expression(expression: str, segments: list[Segment]) -> Decimal:
    """Support arithmetic, a small aggregate-function set, and sheet cell refs."""
    if not expression or len(expression) > 5000:
        raise CalculationError("Expression is empty or too long")

    names: dict[str, Decimal | list[Decimal]] = {}

    def replace_range(match: re.Match[str]) -> str:
        sheet = match.group(1) or (match.group(2) or "").strip()
        cell_range = match.group(3)
        values = _decimal_cell_values(segments, sheet, cell_range)
        name = f"_cell_range_{len(names)}"
        names[name] = values if ":" in cell_range else values[0]
        return name

    source = _SHEET_RANGE.sub(replace_range, expression)
    source = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", source)
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as error:
        raise CalculationError("Expression is not valid arithmetic") from error

    def walk(node: ast.AST) -> Decimal | list[Decimal]:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            try:
                return Decimal(str(node.value))
            except InvalidOperation as error:
                raise CalculationError("Invalid numeric literal") from error
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left = walk(node.left)
            right = walk(node.right)
            if isinstance(left, list) or isinstance(right, list):
                raise CalculationError("A cell range must be used inside an aggregate function")
            try:
                return _BINARY_OPERATORS[type(node.op)](left, right)
            except (DecimalException, ZeroDivisionError) as error:
                raise CalculationError("Division by zero") from error
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = walk(node.operand)
            if isinstance(value, list):
                raise CalculationError("A cell range cannot be signed directly")
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id.upper() in _FUNCTIONS
            and not node.keywords
        ):
            arguments = [walk(argument) for argument in node.args]
            try:
                result = _FUNCTIONS[node.func.id.upper()](*arguments)
            except (DecimalException, ValueError, ZeroDivisionError) as error:
                raise CalculationError(f"Invalid {node.func.id.upper()} arguments") from error
            if not isinstance(result, Decimal):
                raise CalculationError("Calculation did not return a number")
            return result
        raise CalculationError("Expression uses unsupported syntax")

    try:
        result = walk(tree)
    except (DecimalException, ZeroDivisionError) as error:
        raise CalculationError("Division by zero") from error
    if isinstance(result, list) or not result.is_finite():
        raise CalculationError("Calculation did not return a finite number")
    return result


def blank_cells_in_expression(
    expression: str,
    segments: list[Segment],
    preview_limit: int = 40,
) -> tuple[int, list[str]]:
    """Report blank or absent cells inside referenced spreadsheet ranges."""
    cells_by_sheet: dict[str, dict[str, float | str]] = {}
    for segment in segments:
        sheet = segment.locator.sheet
        if sheet and segment.cells:
            cells_by_sheet.setdefault(sheet.casefold(), {}).update(
                {reference.upper(): value for reference, value in segment.cells.items()}
            )

    blank_references: set[str] = set()
    for match in _SHEET_RANGE.finditer(expression):
        sheet = (match.group(1) or match.group(2) or "").strip()
        cell_range = match.group(3)
        if ":" not in cell_range:
            continue
        references = expand_cell_range(cell_range)
        if not references or len(references) > 5000:
            continue
        cells = cells_by_sheet.get(sheet.casefold(), {})
        for reference in references:
            value = cells.get(reference.upper())
            if reference.upper() not in cells or value is None or (
                isinstance(value, str) and not value.strip()
            ):
                blank_references.add(f"{sheet}!{reference.upper()}")

    ordered = sorted(blank_references, key=str.casefold)
    return len(ordered), ordered[:preview_limit]


def calculation_matches(computed: Decimal, stated: Decimal) -> bool:
    """Allow only the rounding implied by the number of digits Gemini returned."""
    exponent = max(0, -stated.as_tuple().exponent)
    tolerance = Decimal("0.5").scaleb(-exponent)
    return abs(computed - stated) <= tolerance


def decimal_text(value: Decimal) -> str:
    """Serialize exact decimal values as plain strings for JSON clients."""
    return format(value, "f")
