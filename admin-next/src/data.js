// 全部实体均为演示数据；就业状态仅用于示意，不代表学校真实就业去向。
export const colleges = [
  { id: 'computer', name: '计算机学院' },
  { id: 'business', name: '经济管理学院' },
  { id: 'manufacturing', name: '智能制造学院' },
];
export const classes = [
  { id: 'software2301', name: '软件工程 2301 班', college: 'computer', counselor: '林老师', grade: '2023' },
  { id: 'cs2302', name: '计算机科学 2302 班', college: 'computer', counselor: '林老师', grade: '2023' },
  { id: 'network2301', name: '网络工程 2301 班', college: 'computer', counselor: '赵老师', grade: '2023' },
  { id: 'business2302', name: '工商管理 2302 班', college: 'business', counselor: '陈老师', grade: '2023' },
  { id: 'marketing2302', name: '市场营销 2302 班', college: 'business', counselor: '吴老师', grade: '2023' },
  { id: 'mechanical2301', name: '机械设计 2301 班', college: 'manufacturing', counselor: '王老师', grade: '2023' },
];
export const students = [
  { id: '2023010101', name: '陈嘉宁', classId: 'software2301', targetRole: '前端开发工程师', employment: 'signed' },
  { id: '2023010102', name: '林子涵', classId: 'software2301', targetRole: '后端开发工程师', employment: 'seeking' },
  { id: '2023020103', name: '王梓阳', classId: 'business2302', targetRole: '产品运营', employment: 'seeking' },
  { id: '2023010204', name: '周雨桐', classId: 'cs2302', targetRole: '数据分析师', employment: 'signed' },
  { id: '2023030105', name: '许知远', classId: 'mechanical2301', targetRole: '机械设计工程师', employment: 'seeking' },
  { id: '2023020206', name: '苏一诺', classId: 'marketing2302', targetRole: '市场专员', employment: 'studying' },
  { id: '2023030107', name: '张宇航', classId: 'mechanical2301', targetRole: '自动化工程师', employment: 'seeking' },
  { id: '2023010208', name: '李沐晴', classId: 'cs2302', targetRole: '算法工程师', employment: 'signed' },
  { id: '2023010309', name: '沈星', classId: 'network2301', targetRole: '网络工程师', employment: 'seeking' },
  { id: '2023010310', name: '陆可欣', classId: 'network2301', targetRole: '网络安全工程师', employment: 'studying' },
];
function dateOffset(days) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
}
export const plans = [
  { id: 'demo-autumn', name: '秋招面试专项训练', description: '从自我介绍到专业表达，为秋招做好准备。', target: { kind: 'all', ids: [] }, role: '通用岗位', type: '综合面试', difficulty: '标准', style: '循循善诱', startDate: dateOffset(-14), deadline: dateOffset(16), status: 'published' },
  { id: 'demo-tech', name: '计算机学院 · 技术面试进阶', description: '提升技术表达与问题分析能力。', target: { kind: 'colleges', ids: ['computer'] }, role: '软件开发工程师', type: '技术面试', difficulty: '进阶', style: '深入追问', startDate: dateOffset(-7), deadline: dateOffset(10), status: 'published' },
  { id: 'demo-intro', name: '职场第一课 · 自我介绍训练', description: '用三分钟，让面试官认识你的优势。', target: { kind: 'colleges', ids: ['business'] }, role: '产品运营', type: '人力资源面试', difficulty: '入门', style: '温和鼓励', startDate: dateOffset(-20), deadline: dateOffset(-2), status: 'published' },
  { id: 'demo-draft', name: '软件工程表达训练', description: '围绕项目经历开展训练。', target: { kind: 'classes', ids: ['software2301'] }, role: '软件开发工程师', type: '技术面试', difficulty: '标准', style: '循循善诱', startDate: dateOffset(2), deadline: dateOffset(14), status: 'draft', ownerRoleId: 'counselor' },
];
// 10 位学生，20 场面试；每人 0–4 场，覆盖无训练、进行中、低分、阈值及零分。
const interviewSeeds = [
  [0, 82, -10, 'demo-autumn'], [0, 88, -6, 'demo-tech'], [0, 92, -1, 'demo-tech'],
  [1, 75, -8, 'demo-autumn'], [1, 63, -3, 'demo-tech'], [1, null, 0, 'demo-tech'],
  [2, 70, -6, 'demo-intro'], [2, null, 0, 'demo-autumn'],
  [3, 89, -2, 'demo-tech'],
  [4, 58, -9, 'demo-autumn'], [4, 62, -1, 'demo-autumn'],
  [5, 76, -12, 'demo-intro'], [5, 78, -5, 'demo-intro'],
  [6, 0, -1, null],
  [7, 81, -13, 'demo-autumn'], [7, 85, -8, 'demo-tech'], [7, 90, -4, 'demo-tech'], [7, 94, -1, 'demo-tech'],
  [8, 65, -3, 'demo-tech'], [8, null, 0, null],
];
export const interviews = interviewSeeds.map(([studentIndex, score, days, planId], index) => {
  const student = students[studentIndex];
  const completed = score !== null;
  return {
    id: 'interview-' + String(index + 1).padStart(3, '0'),
    studentId: student.id,
    planId,
    role: student.targetRole,
    type: plans.find(plan => plan.id === planId)?.type ?? '综合面试',
    startedAt: dateOffset(days) + 'T' + String(9 + index % 8).padStart(2, '0') + ':30:00',
    status: completed ? 'completed' : 'in_progress',
    score,
    grade: !completed ? null : score >= 90 ? '优秀' : score >= 80 ? '良好' : score >= 70 ? '达标' : '待提升',
    dimensions: completed ? [
      { name: '专业知识', score },
      { name: '问题分析', score: Math.max(0, score - 4) },
      { name: '表达沟通', score: Math.min(100, score + 3) },
      { name: '项目实践', score: Math.max(0, score - 2) },
    ] : [],
    agentFeedback: completed ? [
      { name: '技术面试官', feedback: score >= 70 ? '能清晰解释技术选择，建议进一步补充实践证据。' : '基础知识和项目细节仍需巩固，建议先梳理核心概念。' },
      { name: '架构面试官', feedback: '建议从需求、约束和取舍三个层面组织系统设计思路。' },
      { name: '人力资源面试官', feedback: '建议使用具体案例说明协作过程与个人贡献。' },
    ] : [],
    summary: completed ? (score >= 70 ? '整体表达清晰，能够结合经历回答问题。' : '本次训练暴露了基础知识与表达方面的不足，建议安排专项辅导。') : '',
    suggestions: completed ? ['整理一份项目复盘，补充可量化成果。', '围绕目标岗位复习核心知识，并再次进行模拟训练。'] : [],
  };
});
export const followUps = [
  { id: 'follow-seed-1', studentId: '2023030105', status: 'scheduled', note: '已约定本周开展项目表达辅导。', updatedAt: dateOffset(-1) + 'T16:00:00' },
  { id: 'follow-seed-2', studentId: '2023010309', status: 'done', note: '已完成基础知识复盘，后续继续观察训练表现。', updatedAt: dateOffset(-1) + 'T15:00:00' },
];
