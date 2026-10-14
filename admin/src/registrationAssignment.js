export function registrationAssignmentLabel(registration) {
  if (!registration.activated) return '-';
  if (registration.classAssigned === true) return '已归班';
  if (registration.classAssigned === false) return '未归班';
  return '待核对';
}

export function registrationAssignmentCounts(registrations) {
  return registrations.reduce((counts, registration) => {
    if (!registration.activated) return counts;
    if (registration.classAssigned === false) counts.unassigned += 1;
    else if (registration.classAssigned !== true) counts.unknown += 1;
    return counts;
  }, { unassigned: 0, unknown: 0 });
}
