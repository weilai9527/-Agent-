const normalize = (value) => String(value ?? '').trim();

export function resolveRegistrationCounselor(college, selectedClass, classes, registrations) {
  if (!college || !selectedClass) return { counselor: '', source: '', error: '' };

  const configured = normalize(selectedClass.advisor);
  if (configured) return { counselor: configured, source: 'organization', error: '' };

  const className = normalize(selectedClass.name);
  const matchingClasses = classes.filter((item) => (
    item.college_id === college.id && normalize(item.name) === className
  ));
  if (matchingClasses.length > 1) {
    return { counselor: '', source: '', error: `学院内有多个名为「${className}」的班级，无法从学生名单确定辅导员，请先在组织配置中补充。` };
  }

  // 注册名单在账号激活前就包含辅导员，不依赖账号或归班记录。
  const counselors = new Set(registrations
    .filter((item) => normalize(item.college) === normalize(college.name) && normalize(item.className) === className)
    .map((item) => normalize(item.counselor))
    .filter(Boolean));
  if (counselors.size === 1) {
    return { counselor: [...counselors][0], source: 'registrations', error: '' };
  }
  return {
    counselor: '',
    source: '',
    error: counselors.size > 1
      ? `班级「${className}」的学生名单中存在多个辅导员，请先在组织配置中确认该班辅导员。`
      : `班级「${className}」的组织配置和学生名单中均未找到辅导员，请先在组织配置中补充。`,
  };
}
