import { describe, expect, it } from 'vitest';
import { idFromPhone, phone } from './ids';

describe('phone identities', () => {
  it('shows customers and agents by phone number', () => {
    expect(phone('U_777_000001')).toBe('01577000001');
    expect(phone('U_9_0000500')).toBe('01900000500');
    expect(phone('A_777_000001')).toBe('01377000001');
    expect(phone('A_9_000042')).toBe('01390000042');
    expect(phone('A_000042')).toBe('01310000042');
    expect(phone('sup_nadia')).toBe('sup_nadia');
    expect(phone('U_P_01712345678')).toBe('01712345678');
    expect(phone('A_P_01812345678')).toBe('01812345678');
  });

  it('maps a typed number back to the internal ID', () => {
    for (const id of ['U_777_000001', 'U_9_1000003', 'U_42_000010', 'A_9_020000', 'A_000001']) {
      expect(idFromPhone(phone(id))).toBe(id);
    }
    expect(idFromPhone('+880 1577-000001')).toBe('U_777_000001');
    expect(idFromPhone('0157')).toBe('0157');
  });
});
