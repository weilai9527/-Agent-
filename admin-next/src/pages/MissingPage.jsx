import { navigate } from '../router.js';

export default function MissingPage() {
  return (
    <section className="panel empty-state">
      <h1>页面不存在或不在当前角色范围内</h1>
      <p>请切换合适的演示角色，或返回工作台继续浏览。</p>
      <button className="primary section-gap" onClick={() => navigate('/overview')}>返回工作台</button>
    </section>
  );
}
