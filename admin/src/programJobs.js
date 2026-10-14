export function programJobRows(program, availableJobs) {
  const available = new Map(availableJobs.map((job) => [job.id, job]));
  return (program?.jobs || []).map((mapping) => ({
    jobRoleId: mapping.job_role_id,
    priority: mapping.priority === 'optional' ? 'optional' : 'recommended',
    job: available.get(mapping.job_role_id) || { id: mapping.job_role_id, name: mapping.job_name || '原关联岗位' },
    available: available.has(mapping.job_role_id),
  }));
}

export function programJobsPayload(rows) {
  return rows.map(({ jobRoleId, priority }) => ({ jobRoleId, priority }));
}

export function programJobsChanged(rows, saved) {
  const canonical = (items) => JSON.stringify(programJobsPayload(items).sort((a, b) => a.jobRoleId.localeCompare(b.jobRoleId)));
  return canonical(rows) !== canonical(saved);
}
