// 使用当前会话已生效的授权。原生教务从独立页面进入专业配置，不沿用旧库的组织权限。
export function careerPermissions(snapshot) {
  const account = snapshot.admin || {};
  const flags = snapshot.permissions || {};
  const native = snapshot.identityMode === 'native';
  const grants = new Set(account.permissions || []);
  const manager = !native && (account.role === 'super_admin' || grants.has('manageCatalog'));
  const allowed = action => manager || grants.has(action);
  const catalog = allowed('catalog.admin.read') || Boolean(flags.canViewCatalog);
  const programs = !native && Boolean(flags.canViewProgramJobs);
  const readPostings = allowed('posting.admin.read') || Boolean(flags.canViewJobPostings);
  const writePostings = allowed('posting.write');
  const importPostings = allowed('posting.import');
  const syncPostings = allowed('posting.sync');
  const readJds = allowed('jd.read');
  const writeJds = allowed('jd.write');
  const createJds = writeJds && account.actorType === 'admin';
  return {
    canViewCatalog: catalog, canViewProgramJobs: programs,
    canOpenCatalog: programs || catalog || allowed('catalog.write') || allowed('catalog.import') || allowed('catalog.publish'),
    canWriteCatalog: allowed('catalog.write') || Boolean(flags.canWriteCatalog),
    canImportCatalog: allowed('catalog.import') || Boolean(flags.canImportCatalog),
    canPublishCatalog: allowed('catalog.publish') || Boolean(flags.canPublishCatalog),
    canReviewCatalog: allowed('catalog.review'),
    canOpenPostings: readPostings || writePostings || importPostings || syncPostings,
    readPostings, writePostings, importPostings, syncPostings, deletePostings: allowed('posting.delete'),
    canViewMatches: allowed('match.admin.read'),
    canOpenJds: readJds || createJds, readJds, writeJds, createJds,
    approveJds: allowed('jd.approve'), deleteJds: allowed('jd.delete'),
  };
}
