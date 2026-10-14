export function getBrand(pathname = '') {
  return {
    name: /\/xinghe(?:\/|$)/.test(pathname) ? '星河面试' : '乐业通',
    subtitle: '高校面试训练管理平台',
    organization: '就业指导中心',
  };
}
export const brand = getBrand(typeof window === 'undefined' ? '' : window.location.pathname);
export default brand;
