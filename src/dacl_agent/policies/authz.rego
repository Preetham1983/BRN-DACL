# DACL Authorization Policy
# Open Policy Agent (OPA) — Rego v1
#
# This file is the authoritative source of truth for DACL access control.
# It is evaluated inline by authz.py for the current single-node deployment.
# For enterprise/distributed deployment, load this bundle into an OPA sidecar
# and replace the OPAGate._authorize() method with an HTTP call to:
#   POST http://opa:8181/v1/data/dacl/authz/allow
#
# ─────────────────────────────────────────────────────────────────────────────
package dacl.authz

import rego.v1

# ─────────────────────────────────────────────────────────────────────────────
# Role definitions
# ─────────────────────────────────────────────────────────────────────────────

# Map API keys to roles (in production, this comes from a secret store or JWKS)
roles := {
    "admin":   {"compile", "upload", "add_rule", "update_rule", "delete_rule", "rollback", "query", "read"},
    "analyst": {"compile", "add_rule", "update_rule", "query", "read"},
    "reader":  {"query", "read"},
}

# ─────────────────────────────────────────────────────────────────────────────
# Default deny
# ─────────────────────────────────────────────────────────────────────────────

default allow := false

# ─────────────────────────────────────────────────────────────────────────────
# Allow rule — fires when the caller's role has the required permission
# ─────────────────────────────────────────────────────────────────────────────

allow if {
    # input.role is resolved from the API key by the Python layer
    required_permissions := roles[input.role]
    input.permission in required_permissions
}

# ─────────────────────────────────────────────────────────────────────────────
# Open mode — bypass all checks (dev/demo only, never production)
# ─────────────────────────────────────────────────────────────────────────────

allow if {
    input.open_mode == true
}

# ─────────────────────────────────────────────────────────────────────────────
# Denial reason (for structured error messages)
# ─────────────────────────────────────────────────────────────────────────────

deny_reason := msg if {
    not allow
    msg := sprintf(
        "Role '%v' does not have '%v' permission.",
        [input.role, input.permission]
    )
}

deny_reason := "Missing or invalid API key." if {
    not input.role
}
