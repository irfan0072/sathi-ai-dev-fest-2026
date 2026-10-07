// Plain-language labels shared across the console. Users are agents, customers and
// supervisors, not engineers, so every code-like value gets a human name here.

export const roleName = {
  agent: 'Agent',
  customer_channel: 'Customer',
  analyst: 'Fraud analyst',
  supervisor: 'Supervisor',
  super_admin: 'Super admin',
};

export const caseReason = {
  duress_signal: 'Customer asked for help secretly',
  customer_denied_request: 'Customer said “I didn’t ask for this”',
  stated_amount_mismatch: 'Customer said a different amount',
  high_risk_request: 'Request looked risky',
  cash_gap_tolerance_exceeded: 'Customer got less cash than paid',
  repeated_code_failures_lockout: 'Too many wrong codes at the agent',
  post_txn_amount_mismatch: 'Customer typed a different amount',
  customer_denied_transaction: 'Customer says they did not cash out',
};
export const reasonLabel = (reason) => caseReason[reason] || String(reason || '').replaceAll('_', ' ');

export const caseStatus = {
  open: 'Open', escalated: 'Escalated', approved: 'Approved', denied: 'Denied',
};

export const priorityName = { urgent: 'Urgent', high: 'High', normal: 'Normal' };

export const requestStatus = {
  requested: 'Waiting for customer',
  verified: 'Customer confirmed',
  active: 'Code given to agent',
  redeemed: 'Cash paid',
  rejected: 'Stopped',
  expired: 'Expired',
  revoked: 'Cancelled',
};
export const statusLabel = (s) => requestStatus[s] || s;

export const callStatus = {
  queued: 'Calling…',
  ringing: 'Phone is ringing…',
  in_progress: 'Customer is on the call',
  verified: 'Customer confirmed',
  not_verified: 'Customer did not confirm',
  no_answer: 'No answer',
  failed: 'Call failed',
  duress: 'Secret help signal',
  rejected: 'Customer refused',
  mismatch: 'Wrong amount',
};

export const riskLevel = { low: 'Low risk', medium: 'Medium risk', high: 'High risk' };

export const checkNeeded = {
  keypad_or_call: 'Customer can confirm in the app or by phone call',
  call_required: 'Customer must confirm by phone call',
  call_and_review: 'Customer must confirm by phone call, and a supervisor will review it',
};

// Audit log actions, as a person would say them.
export const eventName = {
  cashout_recorded: 'Agent recorded a cash-out',
  txn_check_verified: 'Customer confirmed the amount',
  txn_check_suspicious: 'A cash-out check was marked suspicious (fixed rule: different amount, denial or help signal)',
  mandate_requested: 'Agent asked for a cash-out',
  mandate_verified: 'Customer confirmed the amount',
  mandate_code_issued: 'Agent got the one-time code',
  mandate_redeemed: 'Cash paid out',
  mandate_revoked: 'Request cancelled',
  mandate_expired: 'Request expired',
  mandate_verification_mismatch: 'Customer said a different amount',
  voice_call_placed: 'Confirmation call started',
  voice_call_failed: 'Confirmation call failed',
  voice_duress_signal: 'Customer asked for help secretly',
  voice_customer_denied_request: 'Customer said “I didn’t ask for this”',
  case_brief_generated: 'AI summary created',
  agent_watchlisted: 'Agent put under extra checks',
  agent_unwatchlisted: 'Extra checks removed',
  settings_updated: 'Settings changed',
  settings_reset: 'Setting reset',
  credentials_updated: 'Service keys updated',
  credential_cleared: 'Service key removed',
  provider_tested: 'Service connection tested',
  provider_test_call: 'Test call made',
  provider_test_sms: 'Test SMS sent',
  scam_demo_seeded: 'Scam-seller scenario loaded',
  receiver_flagged: 'Personal account flagged for review',
  ledger_rebased: 'History aligned to today',
  call_task_ignored: 'Customer unreachable after all retries',
  call_task_needs_manual: 'Call sent to a supervisor',
  call_task_claimed: 'Supervisor took a call',
  call_task_assigned: 'Call assigned to a supervisor',
  call_task_released: 'Call put back in the queue',
  call_task_started: 'Supervisor started a call',
  call_task_resolved: 'Supervisor recorded the call result',
  call_task_escalated: 'Call sent to supervisors by admin',
  call_task_callback: 'Call-back scheduled',
  call_task_human_requested: 'Customer asked for a person',
  case_claimed: 'Supervisor took a case',
  case_assigned: 'Case assigned',
  case_released: 'Case put back in the queue',
  case_critical_note: 'Critical note added',
  case_audit_report: 'Case audit filed',
  staff_created: 'Staff member added',
  staff_updated: 'Staff member updated',
  community_report_verified: 'Community report verified',
  community_report_rejected: 'Community report rejected',
  community_report_hidden: 'Community report hidden',
  community_report_published: 'Community report restored',
  voice_call_unclear: 'AI could not understand the answer',
};
export const eventLabel = (action) => eventName[action] || String(action || '').replaceAll('_', ' ');

// Names for the behaviours the AI models look at.
export const featureName = {
  agent_cash_gap_rate: 'Customers who got less cash than paid',
  fee_ratio_vs_official: 'Fee charged compared with the official fee',
  allowance_spike_ratio: 'Extra cash-outs on allowance days',
  agent_assisted_tx_ratio: 'How often an agent does it for them',
  balance_mean: 'Usual account balance',
  credit_to_cashout_hours_mean: 'Time between getting money and cashing out',
  credit_to_cashout_hours_median: 'Usual time between getting money and cashing out',
  credit_to_cashout_hours_min: 'Fastest cash-out after getting money',
  fee_to_amount_ratio: 'Fee compared with the amount',
  pin_entry_seconds_mean: 'Time taken to type the PIN',
  pin_entry_seconds_median: 'Usual time taken to type the PIN',
  session_steps_mean: 'Steps needed to finish a payment',
  withdrawn_balance_ratio_max: 'Share of the balance withdrawn at once',
};
export const featureLabel = (f) => featureName[f] || String(f || '').replaceAll('_', ' ');

// Supervisor view of a post-cash-out check.
export const checkStatus = {
  pending: { label: 'Waiting', tone: 'badge-ghost' },
  calling: { label: 'Calling customer', tone: 'badge-info' },
  verified: { label: 'Verified', tone: 'badge-success' },
  suspicious: { label: 'Suspicious', tone: 'badge-error' },
  no_answer: { label: 'No answer', tone: 'badge-warning' },
};

// What agents and customers see (never the result itself).
export const publicCheck = {
  waiting: { label: 'Confirming with customer…', tone: 'badge-info' },
  done: { label: 'Confirmation done', tone: 'badge-success' },
  missed: { label: 'Customer missed the call', tone: 'badge-warning' },
};

export const takaFmt = (v) => (v == null ? '—' : `৳${Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 })}`);
