// Customers and agents are shown by their upay phone number, never by the internal ID.
// The mapping mirrors sathi_user_msisdn / sathi_agent_msisdn (migration 012), so it needs
// no network call. IDs outside the known namespaces are shown unchanged.
const toPhone = [
  [/^[UA]_P_(01\d{9})$/, (d) => d], // registered test accounts use the real number
  [/^U_9_(\d{7})$/, (d) => `0190${d}`],
  [/^U_42_(\d{6})$/, (d) => `01742${d}`],
  [/^U_4242_(\d{6})$/, (d) => `01842${d}`],
  [/^U_2026_(\d{6})$/, (d) => `01626${d}`],
  [/^U_777_(\d{6})$/, (d) => `01577${d}`],
  [/^A_9_(\d{6})$/, (d) => `01390${d}`],
  [/^A_777_(\d{6})$/, (d) => `01377${d}`],
  [/^A_(\d{6})$/, (d) => `01310${d}`],
];

const toId = [
  [/^0190(\d{7})$/, (d) => `U_9_${d}`],
  [/^01742(\d{6})$/, (d) => `U_42_${d}`],
  [/^01842(\d{6})$/, (d) => `U_4242_${d}`],
  [/^01626(\d{6})$/, (d) => `U_2026_${d}`],
  [/^01577(\d{6})$/, (d) => `U_777_${d}`],
  [/^01390(\d{6})$/, (d) => `A_9_${d}`],
  [/^01377(\d{6})$/, (d) => `A_777_${d}`],
  [/^01310(\d{6})$/, (d) => `A_${d}`],
];

/** Phone number to show for a customer or agent ID. */
export function phone(id) {
  if (!id) return id;
  for (const [re, fmt] of toPhone) {
    const m = re.exec(id);
    if (m) return fmt(m[1]);
  }
  return id;
}

/** Strip spaces, dashes and the +88 country code from a typed number. */
export function normalizePhone(text) {
  const digits = String(text || '').replace(/[\s-]/g, '');
  return digits.replace(/^\+?88(?=01)/, '');
}

/** Internal ID for a typed phone number. Anything else (an ID, a partial number) passes through. */
export function idFromPhone(text) {
  const value = normalizePhone(text);
  for (const [re, fmt] of toId) {
    const m = re.exec(value);
    if (m) return fmt(m[1]);
  }
  return String(text || '').trim();
}
