export const PAGE_SIZE = 6;
export const COACHING_THRESHOLD = 70;
export const INTERVIEW_STATUS = {
  in_progress: { label: '进行中', tone: 'live' },
  completed: { label: '已完成', tone: 'success' },
};
export const FOLLOW_UP_STATUS = {
  pending: { label: '待跟进', tone: 'warning' },
  scheduled: { label: '已安排', tone: 'live' },
  done: { label: '已完成', tone: 'success' },
};
export const PLAN_STATUS = {
  draft: { label: '草稿', tone: 'neutral' },
  upcoming: { label: '未开始', tone: 'neutral' },
  active: { label: '进行中', tone: 'live' },
  ended: { label: '已结束', tone: 'success' },
};
export const EMPLOYMENT_STATUS = {
  seeking: { label: '求职中', tone: 'warning' },
  signed: { label: '已签约', tone: 'success' },
  studying: { label: '升学深造', tone: 'live' },
};
export const INTERVIEW_TYPES = ['综合面试', '技术面试', '架构面试', '人力资源面试'];
export const STORAGE_KEYS = {
  plans: 'interview-admin-user-plans-v1',
  followUps: 'interview-admin-follow-ups-v1',
  preferences: 'interview-admin-preferences-v1',
  role: 'interview-admin-demo-role-v1',
};
