const options = { style: ['友好引导', '专业严谨', '压力面试'], focus: ['项目深挖', '系统设计', '沟通表达'], depth: ['点到为止', '适度深入', '连续深挖'] };
const policy = { studentCanChoose: true, allowed: structuredClone(options), defaults: { style: '专业严谨', focus: '项目深挖', depth: '适度深入' }, roles: {
  technical: { focus: '技术基础与项目实现', strategy: '结合真实项目核对个人职责与实现细节。' },
  architecture: { focus: '系统设计与方案取舍', strategy: '从业务场景切入，逐步核对模块边界。' },
  hr: { focus: '职业动机与沟通协作', strategy: '用具体经历了解行动与协作。' },
} };
module.exports = { options, policy };
