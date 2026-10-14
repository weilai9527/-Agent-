import { LayoutDashboard, Users, BookOpen, KeyRound, Building2, ClipboardList, FileBarChart2, ShieldCheck, BriefcaseBusiness, Target, FileCheck2, Settings2, UserCog, ScrollText, ChartNoAxesCombined } from 'lucide-react';

export const navigation = [
  { label: '总览', items: [{ path: '/overview', label: '工作台', icon: LayoutDashboard }] },
  { label: '学生与教务', items: [
    { path: '/students', label: '学生名单', icon: Users },
    { path: '/classes', label: '班级', icon: BookOpen },
    { path: '/accounts', label: '学生账号', icon: KeyRound, description: '管理学生账号的批量开通与凭据发放。', points: ['表格批量导入学生账号', '生成临时密码', '打印账号发放表'] },
    { path: '/organization', label: '组织架构', icon: Building2, description: '统一维护学校、学院与专业班级信息。', points: ['学院及专业管理', '班级与辅导员分配', '机构名称统一配置'] },
  ] },
  { label: '面试训练', items: [
    { path: '/plans', label: '训练计划', icon: ClipboardList },
    { path: '/interviews', label: '面试记录', icon: FileBarChart2 },
    { path: '/quality', label: '报告质检', icon: ShieldCheck, description: '检查面试报告与评分质量。', points: ['报告抽检与复核', '异常评分核查', '质量问题跟进'] },
  ] },
  { label: '数据分析', items: [{ path: '/employment', label: '就业统计', icon: ChartNoAxesCombined }] },
  { label: '岗位与招聘', items: [
    { path: '/careers', label: '职业目录', icon: Target, description: '维护职业信息并评审智能岗位建议。', points: ['职业目录管理', '人工智能岗位建议池', '岗位对比记录'] },
    { path: '/jobs', label: '招聘岗位', icon: BriefcaseBusiness, description: '维护面向学生的招聘岗位信息。', points: ['招聘岗位发布与维护', '招聘要求与有效期管理'] },
    { path: '/jd-review', label: '岗位描述审核', icon: FileCheck2, description: '审核学生提交的岗位描述。', points: ['学生岗位描述审核', '审核意见与处理记录'] },
  ] },
  { label: '系统', system: true, items: [
    { path: '/models', label: '模型配置', icon: Settings2, description: '管理面试与报告使用的模型策略。', points: ['报告与评分配置', '实时面试配置', '面试官策略', '语音合成配置'] },
    { path: '/admins', label: '管理员与权限', icon: UserCog, description: '管理管理员账号与权限申请。', points: ['管理员管理', '角色与数据范围', '权限申请与审核'] },
    { path: '/security', label: '安全与日志', icon: ScrollText, description: '查询连接状态与安全操作记录。', points: ['连接日志', '安全审计', '数据导出审计'] },
  ] },
];
export function visibleNavigation(role) {
  return navigation.filter(group => !group.system || role.id === 'school');
}
export const pageEntries = navigation.flatMap(group => group.items);
