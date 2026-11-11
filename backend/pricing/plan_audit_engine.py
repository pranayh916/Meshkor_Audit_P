"""Plan audit calculations over approved summaries and verified Parquet references."""
import csv
import hashlib
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings

from pipeline.common import Dose, parse_hcpcs_dosage
from . import data
from .models import DrugUnitReview, NetworkRosterEntry, PlanAudit, PlanAuditResult, SavingsOpportunity


def run_plan_audit(audit, audit_run, heartbeat=None):
    summary_rows = list(audit.summary_import.records.all())
    codes = sorted({row.hcpcs_code for row in summary_rows})
    quarters = sorted({row.quarter for row in summary_rows})
    notes_by_code, scope, approvals, unit_review_hashes = _unit_approvals(codes)
    asp, asp_errors = _asp_rows(codes, quarters)
    hpt, hospital_errors = _hospital_rows(codes, quarters)
    roster = list(NetworkRosterEntry.objects.filter(plan=audit.plan).order_by("provider_npi", "effective_start"))
    site_mapping_hash = _site_mapping_sha256()

    results, result_by_key = [], {}
    for source in summary_rows:
        if heartbeat:
            heartbeat()
        key = (source.hcpcs_code, source.site_npi, source.quarter, source.service_setting)
        notes = list(notes_by_code.get(source.hcpcs_code, []))
        if source.hcpcs_code not in scope:
            notes.append("REFERENCE_NOT_FOUND")
        benchmark = asp.get((source.hcpcs_code, source.quarter))
        if benchmark is None:
            notes.append("REFERENCE_NOT_FOUND")
        unit_ok = source.hcpcs_code in approvals and _asp_unit_matches(
            source.hcpcs_code, benchmark, scope)
        if not unit_ok:
            notes.append("UNIT_UNRESOLVED")

        plan_allowed = _divide(source.total_allowed_amount, source.total_units)
        plan_paid = _divide(source.total_paid_amount, source.total_units)
        asp_limit = _decimal(benchmark.get("payment_limit")) if benchmark else None
        allowed_multiple = _divide(plan_allowed, asp_limit) if unit_ok else None
        paid_multiple = _divide(plan_paid, asp_limit) if unit_ok else None

        hospital = hpt.get((source.hcpcs_code, source.site_npi, source.quarter,
                            source.service_setting))
        hospital_price = _decimal(hospital.get("price")) if hospital else None
        hospital_markup = _divide(hospital_price, asp_limit) if unit_ok else None
        plan_hospital_multiple = _divide(plan_allowed, hospital_price) if unit_ok and hospital_price else None
        if hospital is None:
            notes.append("REFERENCE_NOT_FOUND")

        network_status = network_status_for(roster, source.site_npi, source.quarter)
        if network_status != "IN_NETWORK":
            notes.append(network_status)
        if not notes:
            data_status = "VALID"
        elif "UNIT_UNRESOLVED" in notes:
            data_status = "UNIT_UNRESOLVED"
        elif network_status != "IN_NETWORK":
            data_status = "NETWORK_UNVERIFIED"
        else:
            data_status = "REFERENCE_NOT_FOUND"

        refs = {
            "claims_summary_import_id": audit.summary_import_id,
            "claims_summary_sha256": audit.summary_import.file_hash,
            "asp_source_file": benchmark.get("source_file") if benchmark else None,
            "asp_source_sha256": benchmark.get("source_sha256") if benchmark else None,
            "hospital_price_source_file": hospital.get("source_file") if hospital else None,
            "hospital_price_source_sha256": hospital.get("source_sha256") if hospital else None,
            "hospital_site_mapping_file": "config/hospital_sites.csv",
            "hospital_site_mapping_sha256": site_mapping_hash,
            "network_roster_source_sha256": _roster_source_hashes(roster, source.site_npi, source.quarter),
            "drug_selection_source_sha256": (scope.get(source.hcpcs_code) or {}).get("selection_source_sha256"),
            "unit_review_source_sha256": (unit_review_hashes.get(source.hcpcs_code)
                                          or (scope.get(source.hcpcs_code) or {}).get("unit_review_sha256"))
                                         if unit_ok else None,
            "unit_review_status": "validated" if unit_ok else "unresolved",
            "unit_review_billing_qty": ((scope.get(source.hcpcs_code) or {}).get("billing_unit") or {}).get("qty")
                                       if unit_ok else None,
            "unit_review_billing_unit": ((scope.get(source.hcpcs_code) or {}).get("billing_unit") or {}).get("unit")
                                        if unit_ok else None,
        }
        result = PlanAuditResult(
            plan_audit=audit, audit_run=audit_run, summary_record=source,
            hcpcs_code=source.hcpcs_code,
            drug_description=str(benchmark.get("short_description") or "")[:240] if benchmark else "",
            site_npi=source.site_npi,
            quarter=source.quarter, service_setting=source.service_setting,
            total_units=source.total_units, total_allowed_amount=source.total_allowed_amount,
            total_paid_amount=source.total_paid_amount, member_count_band=source.member_count_band,
            plan_allowed_price_per_unit=plan_allowed,
            plan_paid_price_per_unit=plan_paid,
            hospital_price_per_unit=hospital_price, asp_payment_limit=asp_limit,
            hospital_markup_multiple=hospital_markup, allowed_markup_multiple=allowed_multiple, paid_markup_multiple=paid_multiple,
            plan_to_hospital_price_multiple=plan_hospital_multiple,
            network_status=network_status, data_quality_status=data_status,
            data_quality_notes=sorted(set(notes)), source_references=refs,
        )
        results.append(result)
        result_by_key[key] = (source, result, unit_ok)

    opportunities = _build_opportunities(audit, audit_run, summary_rows, result_by_key, roster)
    # Fence the final result write and keep it atomic. A stale worker cannot pass
    # the owner check and then race a new reservation while writing these rows.
    from django.db import transaction
    with transaction.atomic():
        owns_audit = PlanAudit.objects.select_for_update().filter(
            pk=audit.pk, current_version=audit_run.version,
            run_owner_token=audit_run.worker_id,
        ).exists()
        if not owns_audit:
            if heartbeat:
                heartbeat()
            raise RuntimeError("Audit run ownership was lost before result persistence.")
        if heartbeat:
            heartbeat()
        PlanAuditResult.objects.bulk_create(results, batch_size=1000)
        SavingsOpportunity.objects.bulk_create(opportunities, batch_size=1000)
    quality_counts = defaultdict(int)
    for result in results:
        quality_counts[result.data_quality_status] += 1
    return {
        "result_rows": len(results),
        "quality_status_counts": dict(quality_counts),
        "savings_opportunities": len(opportunities),
        "reference_errors": asp_errors + hospital_errors,
        "totals_scope": "visible_approved_aggregate_rows_only",
    }


def _unit_approvals(codes):
    scope = {}
    approvals = set()
    review_hashes = {}
    notes = defaultdict(list)
    try:
        current_scope = data.drug_config()
        scope = {code: current_scope[code] for code in codes if code in current_scope}
        run = data.run_info()
        current_hash = run.get("drug_selection_source_sha256")
        if current_hash:
            reviews = DrugUnitReview.objects.filter(
                hcpcs__in=codes, scope_source_sha256=current_hash, status="validated"
            )
            for review in reviews:
                item = scope.get(review.hcpcs)
                unit = item.get("billing_unit") if item else None
                if (unit and _decimal(unit.get("qty")) == review.billing_qty
                        and str(unit.get("unit", "")).upper() == review.billing_unit.upper()):
                    approvals.add(review.hcpcs)
                    review_hashes[review.hcpcs] = review.scope_source_sha256
                else:
                    notes[review.hcpcs].append("UNIT_UNRESOLVED")
    except (data.DataMissing, OSError, ValueError, KeyError):
        for code in codes:
            notes[code].append("REFERENCE_NOT_FOUND")
    for code in codes:
        if code not in approvals:
            notes[code].append("UNIT_UNRESOLVED")
    return notes, scope, approvals, review_hashes


def _asp_rows(codes, quarters):
    if not codes or not quarters:
        return {}, 0
    try:
        placeholders = ",".join("?" for _ in codes)
        q_placeholders = ",".join("?" for _ in quarters)
        rows = data.query(
            f"SELECT hcpcs, quarter, payment_limit, dosage_text, short_description, source_file, source_sha256 "
            f"FROM {{asp}} WHERE hcpcs IN ({placeholders}) AND quarter IN ({q_placeholders})",
            [*codes, *quarters], asp="asp",
        )
        return {(row["hcpcs"], row["quarter"]): row for row in rows}, 0
    except (data.DataMissing, OSError, ValueError):
        return {}, 1


def _hospital_rows(codes, quarters):
    name_to_npi = _verified_site_names()
    if not codes or not quarters or not name_to_npi:
        return {}, 0
    placeholders = ",".join("?" for _ in codes)
    q_placeholders = ",".join("?" for _ in quarters)
    try:
        rows = data.query(
            f"SELECT hcpcs, hospital_label, setting, benchmark_quarter, price_per_billing_unit, "
            f"billing_units, status, price_type, source_file, source_sha256, effective_start, effective_end "
            f"FROM {{comparison}} WHERE hcpcs IN ({placeholders}) "
            f"AND benchmark_quarter IN ({q_placeholders}) "
            f"AND price_type = 'negotiated_dollar' AND status = 'ok' "
            f"AND price_per_billing_unit IS NOT NULL AND billing_units > 0",
            [*codes, *quarters], comparison="comparison",
        )
    except (data.DataMissing, OSError, ValueError):
        return {}, 1

    candidates = defaultdict(list)
    for row in rows:
        label_key = _normalize_name(row.get("hospital_label"))
        mapped_npis = name_to_npi.get(label_key, set())
        if len(mapped_npis) != 1:
            continue
        npi = next(iter(mapped_npis))
        if not _rate_covers_quarter(row, row.get("benchmark_quarter")):
            continue
        key = (row["hcpcs"], npi, row["benchmark_quarter"], row.get("setting") or "unknown")
        candidates[key].append(row)
    resolved = {}
    for key, matches in candidates.items():
        values = {_decimal(item.get("price_per_billing_unit")) for item in matches}
        values.discard(None)
        # Distinct payer or plan rates are not interchangeable. Only an unambiguous
        # single published dollar value is retained as a hospital reference.
        if len(values) != 1:
            continue
        match = matches[0]
        resolved[key] = {
            "price": next(iter(values)),
            "source_file": match.get("source_file"),
            "source_sha256": match.get("source_sha256"),
        }
    return resolved, 0


def _site_mapping_sha256():
    path = settings.BASE_DIR.parent / "config" / "hospital_sites.csv"
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_site_names():
    path = settings.BASE_DIR.parent / "config" / "hospital_sites.csv"
    name_to_npi = defaultdict(set)
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                npi = str(row.get("npi") or "").strip()
                name = str(row.get("hospital_name") or "").strip()
                if (not _valid_npi(npi) or not name or not row.get("source")
                        or not row.get("verified_on")):
                    continue
                try:
                    verified_on = date.fromisoformat(row["verified_on"].strip())
                except ValueError:
                    continue
                if verified_on > date.today():
                    continue
                name_to_npi[_normalize_name(name)].add(npi)
    except OSError:
        return {}
    return name_to_npi


def _build_opportunities(audit, audit_run, rows, result_by_key, roster):
    by_group = defaultdict(list)
    for source in rows:
        key = (source.hcpcs_code, source.site_npi, source.quarter, source.service_setting)
        record, result, unit_ok = result_by_key[key]
        if not unit_ok or result.plan_allowed_price_per_unit is None:
            continue
        by_group[(source.hcpcs_code, source.quarter, source.service_setting)].append(
            (record, result)
        )

    opportunities = []
    for (code, quarter, setting), group in by_group.items():
        alternatives_by_npi = {
            record.site_npi: (record, result)
            for record, result in group
            if network_status_for(roster, record.site_npi, quarter) == "IN_NETWORK"
        }
        for current, current_result in group:
            current_price = current_result.plan_allowed_price_per_unit
            if current_price is None:
                continue
            lower = [
                (record, result) for npi, (record, result) in alternatives_by_npi.items()
                if npi != current.site_npi and result.plan_allowed_price_per_unit is not None
                and result.plan_allowed_price_per_unit < current_price
            ]
            if not lower:
                continue
            alternative, alternative_result = min(
                lower, key=lambda pair: (pair[1].plan_allowed_price_per_unit, pair[0].site_npi)
            )
            savings = (current_price - alternative_result.plan_allowed_price_per_unit) * current.total_units
            if savings <= 0:
                continue
            paid_difference = None
            if (current_result.plan_paid_price_per_unit is not None
                    and alternative_result.plan_paid_price_per_unit is not None):
                paid_difference = (current_result.plan_paid_price_per_unit -
                                   alternative_result.plan_paid_price_per_unit) * current.total_units
            opportunities.append(SavingsOpportunity(
                plan_audit=audit, audit_run=audit_run, hcpcs_code=code, quarter=quarter, service_setting=setting,
                current_site_npi=current.site_npi, alternative_site_npi=alternative.site_npi,
                current_allowed_price_per_unit=current_price,
                alternative_allowed_price_per_unit=alternative_result.plan_allowed_price_per_unit,
                units=current.total_units, potential_allowed_savings=savings,
                potential_paid_difference=paid_difference, network_status="IN_NETWORK",
                clinical_review_status="pending",
                validation_status="pending",
                source_references={
                    "claims_summary_sha256": audit.summary_import.file_hash,
                    "network_roster_file_hashes": _roster_source_hashes(roster, alternative.site_npi, quarter),
                    "alternative_is_claims_observed": True,
                },
            ))
    return opportunities


def _roster_source_hashes(roster, npi, quarter):
    start, end = _quarter_bounds(quarter)
    return sorted({entry.source_hash for entry in roster
                   if entry.provider_npi == npi and entry.effective_start <= end
                   and (entry.effective_end is None or entry.effective_end >= start)})


def network_status_for(roster, npi, quarter):
    start, end = _quarter_bounds(quarter)
    records = [item for item in roster if item.provider_npi == npi]
    if not records:
        return "NETWORK_STATUS_UNKNOWN"

    overlapping = []
    expired = []
    for item in records:
        record_start, record_end = item.effective_start, item.effective_end
        if record_start is None or (record_end is not None and record_end < record_start):
            return "NETWORK_STATUS_UNKNOWN"
        if record_end is not None and record_end < start:
            expired.append(item)
            continue
        if record_start > end:
            continue
        if record_start <= end and (record_end is None or record_end >= start):
            overlapping.append(item)
    if not overlapping:
        if expired and len(expired) == len(records):
            return "NETWORK_DATA_EXPIRED"
        return "NETWORK_STATUS_UNKNOWN"

    # The audit supplies a plan and provider NPI, but no network-contract or
    # service-location selector. Multiple such identities cannot be resolved safely.
    identities = set()
    plan_ids = set()
    for item in overlapping:
        network_name = str(item.network_name or "").strip().casefold()
        service_location = str(item.service_location or "").strip().casefold()
        source_hash = str(item.source_hash or "").lower()
        if (not network_name or not service_location or len(source_hash) != 64
                or any(char not in "0123456789abcdef" for char in source_hash)):
            return "NETWORK_STATUS_UNKNOWN"
        identities.add((network_name, service_location))
        if item.plan_id is None:
            return "NETWORK_STATUS_UNKNOWN"
        plan_ids.add(item.plan_id)
    if len(identities) != 1 or len(plan_ids) != 1:
        return "NETWORK_STATUS_UNKNOWN"

    quarter_end_exclusive = end + timedelta(days=1)
    events = defaultdict(lambda: {"add": [], "remove": []})
    for item in overlapping:
        status = str(item.network_status or "").strip().casefold()
        if status not in {"in_network", "out_of_network"}:
            return "NETWORK_STATUS_UNKNOWN"
        clipped_start = max(start, item.effective_start)
        clipped_end = min(end, item.effective_end) if item.effective_end else end
        events[clipped_start]["add"].append(status)
        events[clipped_end + timedelta(days=1)]["remove"].append(status)

    boundaries = sorted({start, quarter_end_exclusive, *events})
    active = Counter()
    consistent_status = None
    for index, boundary in enumerate(boundaries[:-1]):
        for status in events[boundary]["remove"]:
            active[status] -= 1
            if active[status] <= 0:
                del active[status]
        for status in events[boundary]["add"]:
            active[status] += 1
        if boundaries[index + 1] <= boundary:
            continue
        if not active or len(active) != 1:
            return "NETWORK_STATUS_UNKNOWN"
        status = next(iter(active))
        if consistent_status is None:
            consistent_status = status
        elif status != consistent_status:
            return "NETWORK_STATUS_UNKNOWN"

    if consistent_status == "in_network":
        return "IN_NETWORK"
    if consistent_status == "out_of_network":
        return "OUT_OF_NETWORK"
    return "NETWORK_STATUS_UNKNOWN"


def _rate_covers_quarter(row, quarter):
    start, end = _quarter_bounds(quarter)
    rate_start, rate_end = row.get("effective_start"), row.get("effective_end")
    return (rate_start is None or rate_start <= start) and (rate_end is None or rate_end >= end)


def _quarter_bounds(quarter):
    match = re.fullmatch(r"(20\d{2})Q([1-4])", str(quarter))
    if not match:
        raise ValueError("Invalid reporting quarter.")
    year, q = int(match.group(1)), int(match.group(2))
    month = 1 + (q - 1) * 3
    start = date(year, month, 1)
    next_month = month + 3
    end = date(year + (next_month > 12), 1 if next_month > 12 else next_month, 1)
    return start, date.fromordinal(end.toordinal() - 1)


def _normalize_name(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _valid_npi(value):
    if not re.fullmatch(r"\d{10}", str(value or "")):
        return False
    digits = [int(digit) for digit in "80840" + str(value)]
    total = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2:
            digit = digit * 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _asp_unit_matches(code, benchmark, scope):
    if not benchmark or code not in scope:
        return False
    unit = scope[code].get("billing_unit") or {}
    try:
        config_dose = Dose(float(unit["qty"]), str(unit["unit"]).upper())
        asp_dose = parse_hcpcs_dosage(benchmark.get("dosage_text"))
        return asp_dose == config_dose
    except (KeyError, TypeError, ValueError):
        return False


def _decimal(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def _divide(numerator, denominator):
    n, d = _decimal(numerator), _decimal(denominator)
    if n is None or d is None or d <= 0:
        return None
    return n / d
