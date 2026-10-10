// Both names use the same application and assets. The URL only selects the name.
const path = typeof window === 'undefined' ? '/' : window.location.pathname;
const segments = path.split('/').filter(Boolean);

export const brand = Object.freeze({
  name: segments.includes('xinghe') ? '星河面试' : '乐业通',
});
