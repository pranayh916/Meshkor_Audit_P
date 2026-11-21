const ROLE_ALIASES = {
  SUPER_ADMIN: ["SUPER_ADMIN", "Admin"],
  ANALYST: ["ANALYST"],
  REVIEWER: ["REVIEWER"],
  CLIENT: ["CLIENT", "Viewer"],
};

export function hasRole(user, ...roles) {
  const assigned = new Set(user?.roles || []);
  return roles.some((role) => (ROLE_ALIASES[role] || [role]).some((alias) => assigned.has(alias)));
}

export function workspaceRole(user) {
  if (hasRole(user, "SUPER_ADMIN")) return "SUPER_ADMIN";
  if (hasRole(user, "ANALYST")) return "ANALYST";
  if (hasRole(user, "REVIEWER")) return "REVIEWER";
  if (hasRole(user, "CLIENT")) return "CLIENT";
  return null;
}

export const ROLE_POLICY = {
  admin: ["SUPER_ADMIN"],
  analyst: ["SUPER_ADMIN", "ANALYST"],
  reviewer: ["SUPER_ADMIN", "REVIEWER"],
  client: ["CLIENT"],
  planAudits: ["SUPER_ADMIN", "ANALYST", "REVIEWER", "CLIENT"],
  claims: ["SUPER_ADMIN", "ANALYST"],
  drugScope: ["SUPER_ADMIN", "ANALYST", "REVIEWER"],
  market: ["SUPER_ADMIN", "ANALYST", "REVIEWER", "CLIENT"],
  account: ["SUPER_ADMIN", "ANALYST", "REVIEWER", "CLIENT"],
};

export function canAccess(user, policy) {
  return hasRole(user, ...(ROLE_POLICY[policy] || []));
}

export function isClientOnly(user) {
  return hasRole(user, "CLIENT") && !hasRole(user, "SUPER_ADMIN", "ANALYST", "REVIEWER");
}
