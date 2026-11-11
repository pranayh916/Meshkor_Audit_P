export function compareTableValues(left, right, { numeric = false, direction = "asc" } = {}) {
  if (left == null) return right == null ? 0 : 1;
  if (right == null) return -1;

  let comparison;
  if (numeric) {
    const leftNumber = Number(left);
    const rightNumber = Number(right);
    if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
      comparison = leftNumber < rightNumber ? -1 : leftNumber > rightNumber ? 1 : 0;
    }
  }
  if (comparison == null) {
    comparison = String(left).localeCompare(String(right));
  }
  return comparison * (direction === "desc" ? -1 : 1);
}
