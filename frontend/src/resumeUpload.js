export async function uploadResume(url, file, request = fetch) {
  if (!/\.(pdf|docx|txt|md)$/i.test(file.name)) {
    throw new Error('请选择 PDF、DOCX、TXT 或 Markdown 格式的简历。');
  }
  if (!file.size || file.size > 10 * 1024 * 1024) {
    throw new Error('请选择有内容且不超过 10 MB 的简历文件。');
  }
  const body = new FormData();
  body.append('file', file);
  const response = await request(url, { method: 'POST', credentials: 'include', body });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error('上传服务暂时不可用，请稍后重试。');
  }
  if (!response.ok) {
    throw new Error(typeof data.detail === 'string' ? data.detail : data.error || '上传失败，请重试。');
  }
  if (typeof data.text !== 'string' || !data.text.trim()) {
    throw new Error('未能提取简历内容，请更换文件或直接粘贴文本。');
  }
  return data;
}
