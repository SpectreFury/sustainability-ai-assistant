import json


SPREADSHEET_MAPPING_SYSTEM_PROMPT = """
Map only provided headers; never infer or return cell values. Map numeric columns
as metric_columns with a snake_case name and the unit shown in the header. For
long-form tables, map metric_name_column and metric_value_column. Map period,
FY, and unit columns when available. Use zero-based indexes. Ignore identifiers
and prices unless their headers clearly describe metrics.
""".strip()


def spreadsheet_mapping_input(headers: list[str]) -> str:
    return json.dumps(
        {
            "headers": [
                {"column_index": index, "header": header or "(blank)"}
                for index, header in enumerate(headers)
            ]
        }
    )
