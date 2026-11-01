// SPDX-License-Identifier: AGPL-3.0-or-later
const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

/** A timestamp from the API, formatted for the viewer's locale. */
export const when = (iso: string) => dateTime.format(new Date(iso));

/**
 * A decimal string from the API ("120.5000000000") without trailing zeros,
 * with thousands separators. Works on the string, so no precision is lost.
 */
export function amount(value: string): string {
  const [whole = '0', fraction = ''] = value.split('.');
  const negative = whole.startsWith('-');
  const digits = negative ? whole.slice(1) : whole;
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const trimmed = fraction.replace(/0+$/, '');
  return `${negative ? '-' : ''}${grouped}${trimmed ? `.${trimmed}` : ''}`;
}

/** A decimal string without trailing zeros or separators, for editing in a form. */
export const plain = (value: string) => amount(value).replaceAll(',', '');

const SYMBOLS: Record<string, string> = { GBP: '£', USD: '$', EUR: '€' };

/** An amount in an instrument's quote currency. GBX is pence, as LSE quotes are. */
export function money(value: string, currency: string): string {
  const text = amount(value);
  if (currency === 'GBX') return `${text}p`;
  const symbol = SYMBOLS[currency];
  if (!symbol) return `${text} ${currency}`;
  // Pounds, dollars and euros always show pence or cents: $77,519.40, not $77,519.4.
  const decimals = text.split('.')[1]?.length ?? 0;
  const padded =
    decimals >= 2 ? text : `${text}${decimals === 0 ? '.' : ''}${'0'.repeat(2 - decimals)}`;
  return `${symbol}${padded}`;
}
