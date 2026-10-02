# Concrete migration002 clarification — human approved

The approved design allows NULL code_hash only in requested/verified states. Rejection, expiry or revocation can happen before terminal code issuance, so those legitimate transitions would violate that constraint or require an artificial hash.

Proposed correction: permit NULL for requested, verified, rejected, expired and revoked; require a64-character hash for active/redeemed. Any non-NULL hash must have64hex characters. Preserve every existing row/hash and migration001 checksum. Retain attempt counters/live-user uniqueness/confirmation uniqueness and all approved API/scopes. Never fabricate a code/hash to satisfy a terminal state. No new API or authority.

Approval required because this narrows the approved schema constraint to match actual unissued terminal states; resume brief requires schema changes proposed before implementation. T023 proceeds independently; do not implement migration002 until this clarification is approved.

Human approved on2October2026: Approve the nullability clarification.
