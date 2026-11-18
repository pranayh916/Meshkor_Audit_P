import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


REQUIRED_FIELDS = {
    "claim_id", "service_date", "hcpcs_code", "site_npi", "units",
    "allowed_amount", "paid_amount", "member_id", "claim_status", "plan_id",
}
OPTIONAL_FIELDS = {"adjustment_reference", "reversal_reference", "service_setting"}
HCPCS_PATTERN = re.compile(r"^[A-Z0-9]\d{3}[A-Z0-9]$")
NPI_PATTERN = re.compile(r"^\d{10}$")


def normalize_header(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")


def normalize_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def claim_chain_context(row, source_row):
    """Return only local identifiers/references needed to quarantine a bad row."""
    normalized = {normalize_header(key): value for key, value in row.items()}
    claim_id = normalize_text(normalized.get("claim_id"))
    adjustment_reference = normalize_text(normalized.get("adjustment_reference"))
    reversal_reference = normalize_text(normalized.get("reversal_reference"))
    if not (claim_id or adjustment_reference or reversal_reference):
        return None
    return {
        "claim_id": claim_id,
        "adjustment_reference": adjustment_reference,
        "reversal_reference": reversal_reference,
        "source_row": source_row,
    }


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = normalize_text(value)
    if not raw:
        raise ValueError("service_date is required")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        try:
            return datetime.fromisoformat(raw).date()
        except ValueError:
            raise ValueError("service_date must be an ISO date or ISO datetime") from exc


def parse_decimal(value, field, *, positive=False):
    raw = normalize_text(value)
    try:
        result = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal amount") from exc
    if not result.is_finite() or result < 0 or (positive and result <= 0):
        qualifier = "greater than zero" if positive else "a non-negative finite amount"
        raise ValueError(f"{field} must be {qualifier}")
    normalized = result.normalize()
    scale = max(-normalized.as_tuple().exponent, 0)
    integer_digits = max(normalized.adjusted() + 1, 0) if result else 1
    if scale > 6 or integer_digits > 18:
        raise ValueError(f"{field} supports at most 18 integer and 6 decimal digits")
    return result


def valid_npi(value):
    raw = normalize_text(value)
    if not NPI_PATTERN.fullmatch(raw):
        return False
    digits = [int(digit) for digit in "80840" + raw]
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def validate_claim(row, source_row):
    normalized = {normalize_header(key): value for key, value in row.items()}
    if normalized.get("extra_columns"):
        raise ValueError("Row has more fields than the header.")
    missing = sorted(field for field in REQUIRED_FIELDS if not normalize_text(normalized.get(field)))
    if missing:
        raise ValueError("Missing required fields: " + ", ".join(missing))
    claim = {field: normalize_text(normalized.get(field)) for field in REQUIRED_FIELDS | OPTIONAL_FIELDS}
    claim["service_date"] = parse_date(normalized.get("service_date"))
    claim["hcpcs_code"] = claim["hcpcs_code"].upper()
    if not HCPCS_PATTERN.fullmatch(claim["hcpcs_code"]):
        raise ValueError("hcpcs_code is not a valid five-character HCPCS code")
    if not valid_npi(claim["site_npi"]):
        raise ValueError("site_npi is not a valid 10-digit NPI")
    claim["units"] = parse_decimal(normalized.get("units"), "units", positive=True)
    claim["allowed_amount"] = parse_decimal(normalized.get("allowed_amount"), "allowed_amount")
    claim["paid_amount"] = parse_decimal(normalized.get("paid_amount"), "paid_amount")
    claim["claim_status"] = claim["claim_status"].casefold().replace(" ", "_")
    allowed_statuses = {"paid", "approved", "adjusted", "reversed", "denied"}
    if claim["claim_status"] not in allowed_statuses:
        raise ValueError("claim_status must be paid, approved, adjusted, reversed, or denied")
    if claim["claim_status"] == "adjusted" and not claim["adjustment_reference"]:
        raise ValueError("adjusted claims require adjustment_reference")
    if claim["claim_status"] == "reversed" and not claim["reversal_reference"]:
        raise ValueError("reversed claims require reversal_reference")
    if claim["claim_status"] != "adjusted" and claim["adjustment_reference"]:
        raise ValueError("adjustment_reference is valid only for adjusted claims")
    if claim["claim_status"] != "reversed" and claim["reversal_reference"]:
        raise ValueError("reversal_reference is valid only for reversed claims")
    if claim["adjustment_reference"] and claim["reversal_reference"]:
        raise ValueError("A row cannot be both an adjustment and a reversal")
    claim["service_setting"] = claim["service_setting"].casefold() or "unknown"
    if not re.fullmatch(r"[a-z0-9][a-z0-9 _./-]{0,79}", claim["service_setting"]):
        raise ValueError("service_setting contains unsupported characters or begins with a formula prefix")
    claim["source_row"] = source_row
    return claim
