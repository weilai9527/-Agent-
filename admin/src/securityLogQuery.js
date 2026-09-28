export function securityLogParams(query) {
  // Optional dates must be omitted: an empty date is rejected by the API.
  return new URLSearchParams(Object.entries({ limit: 50, ...query })
    .filter(([, value]) => value !== '' && value !== null && value !== undefined));
}
