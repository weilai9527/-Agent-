export function mergeProfileIntoSetup(current, profile = {}, mode = 'guided', options = {}) {
  const preserveBrief = Boolean(options.preserveBrief);
  const shared = {
    ...current,
    role: profile.target_role || current.role,
    brief: preserveBrief
      ? current.brief
      : profile.project_experience || profile.resume_text || current.brief,
  };

  if (mode !== 'custom') return shared;

  return {
    ...shared,
    level: profile.experience_level || current.level,
    interviewType: profile.preferred_interview_type || current.interviewType,
    intensity: profile.preferred_difficulty || current.intensity,
    style: profile.preferred_interviewer_style || current.style,
  };
}
