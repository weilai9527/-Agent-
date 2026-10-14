export function securityLogParams(query) {
  // Optional dates must be omitted: an empty date is rejected by the API.
  const { fixedUntil, ...parameters } = query;
  return new URLSearchParams(Object.entries({ limit: 50, ...parameters })
    .filter(([, value]) => value !== '' && value !== null && value !== undefined));
}
