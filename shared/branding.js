// 两种品牌共用前端和资源，访问路径只决定显示名称。
const path = typeof window === 'undefined' ? '/' : window.location.pathname;
const segments = path.split('/').filter(Boolean);

export const brand = Object.freeze({
  name: segments.includes('xinghe') ? '星河面试' : '乐业通',
});
