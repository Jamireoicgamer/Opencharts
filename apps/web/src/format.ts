// SPDX-License-Identifier: AGPL-3.0-or-later
const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

/** A timestamp from the API, formatted for the viewer's locale. */
export const when = (iso: string) => dateTime.format(new Date(iso));
