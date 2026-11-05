export function securityLogParams(query) {
  // 未选择日期时省略相应参数，接口会拒绝空日期。
  const { fixedUntil, ...parameters } = query;
  return new URLSearchParams(Object.entries({ limit: 50, ...parameters })
    .filter(([, value]) => value !== '' && value !== null && value !== undefined));
}
