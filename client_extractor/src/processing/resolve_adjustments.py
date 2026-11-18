from collections import defaultdict, deque


_CONTEXT_FIELDS = ("member_id", "plan_id", "hcpcs_code", "site_npi", "service_date")
_RESOLVED_STATUSES = {"paid", "approved", "adjusted", "reversed", "denied"}


def resolve_claims(claims, quality, quarantined=()):
    """Resolve complete claim chains; fail closed on ambiguous dependencies."""
    by_id = defaultdict(list)
    for claim in claims:
        by_id[claim["claim_id"]].append(claim)

    invalid = {claim_id for claim_id, rows in by_id.items() if len(rows) > 1}
    children = defaultdict(set)
    action_counts = defaultdict(int)
    action_by_target = {}

    # Invalid source rows never enter calculation, but their local references
    # still quarantine any claim they could have replaced or reversed.
    for context in quarantined:
        claim_id = context.get("claim_id")
        if claim_id:
            invalid.add(claim_id)
        for reference in (context.get("adjustment_reference"),
                          context.get("reversal_reference")):
            if reference:
                invalid.add(reference)

    for claim in claims:
        claim_id = claim["claim_id"]
        status = claim["claim_status"]
        if status not in _RESOLVED_STATUSES:
            invalid.add(claim_id)
            continue
        reference = _reference_for(claim)
        if not reference:
            if status in {"adjusted", "reversed"}:
                invalid.add(claim_id)
            continue

        targets = by_id.get(reference, ())
        if len(targets) != 1:
            invalid.add(claim_id)
            continue

        target = targets[0]
        children[reference].add(claim_id)
        action_counts[reference] += 1
        action_by_target[reference] = claim
        if reference == claim_id:
            invalid.add(claim_id)
            continue
        if any(target[field] != claim[field] for field in _CONTEXT_FIELDS):
            invalid.update((claim_id, reference))
        if target["claim_status"] in {"denied", "reversed"}:
            invalid.add(claim_id)

    # A predecessor can have only one replacement or reversal. Even identical
    # duplicate action rows count as competing source records.
    for target_id, count in action_counts.items():
        if count > 1:
            invalid.add(target_id)
            invalid.update(children[target_id])

    # Kahn's algorithm detects cycles without recursion. Remaining nodes include
    # cycle members and every descendant that depends on a cycle.
    indegree = {claim_id: 0 for claim_id in by_id}
    for descendants in children.values():
        for child_id in descendants:
            indegree[child_id] += 1
    ready = deque(claim_id for claim_id, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        claim_id = ready.popleft()
        visited += 1
        for child_id in children.get(claim_id, ()):
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                ready.append(child_id)
    if visited != len(indegree):
        invalid.update(claim_id for claim_id, degree in indegree.items() if degree > 0)

    # Propagate every invalid root through the full dependent subgraph.
    pending = deque(invalid)
    while pending:
        claim_id = pending.popleft()
        for child_id in children.get(claim_id, ()):
            if child_id not in invalid:
                invalid.add(child_id)
                pending.append(child_id)

    superseded = {target_id for target_id, count in action_counts.items() if count == 1}
    output = []
    for claim in claims:
        claim_id = claim["claim_id"]
        status = claim["claim_status"]
        if claim_id in invalid:
            _reason(quality, "unresolved_adjustment_or_duplicate")
        elif status == "denied":
            _reason(quality, "denied_claim")
        elif status == "reversed":
            quality["reversed_records"] += 1
            _reason(quality, "reversal_transaction")
        elif claim_id in superseded:
            action = action_by_target[claim_id]
            if action["claim_status"] == "reversed":
                quality["reversed_records"] += 1
                _reason(quality, "reversed_original_claim")
            else:
                quality["adjusted_records"] += 1
                _reason(quality, "superseded_by_adjustment")
        elif status in {"paid", "approved", "adjusted"}:
            output.append(claim)

    return sorted(output, key=lambda claim: claim["claim_id"])


def _reference_for(claim):
    if claim["claim_status"] == "adjusted":
        return claim.get("adjustment_reference", "")
    if claim["claim_status"] == "reversed":
        return claim.get("reversal_reference", "")
    return ""


def _reason(quality, reason):
    quality["reasons"][reason] = quality["reasons"].get(reason, 0) + 1
    quality["excluded_records"] += 1
