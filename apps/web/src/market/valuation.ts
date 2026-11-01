// SPDX-License-Identifier: AGPL-3.0-or-later
// Market value and profit of holdings, for display. Totals stay per
// currency: nothing is converted between currencies yet.

/** Holdings priced in pence are valued in pounds. */
export const valuationCurrency = (currency: string) => (currency === 'GBX' ? 'GBP' : currency);
const factor = (currency: string) => (currency === 'GBX' ? 0.01 : 1);

export function marketValue(quantity: string, price: string, currency: string): number {
  return Number(quantity) * Number(price) * factor(currency);
}

/** Unrealised profit, or null without an average price. */
export function profit(
  quantity: string,
  averagePrice: string | null,
  price: string,
  currency: string,
): number | null {
  if (averagePrice === null) return null;
  return Number(quantity) * (Number(price) - Number(averagePrice)) * factor(currency);
}

export function cash(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      maximumFractionDigits: 2,
      minimumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

/** "+£12.34" / "-$5.00" */
export const signedCash = (value: number, currency: string) =>
  `${value > 0 ? '+' : ''}${cash(value, currency)}`;
