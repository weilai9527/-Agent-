/** 同一学校管理网关使用有界 JSON 请求传递文件，避免浏览器缓存和表单解析产生凭据副本。 */
export function encodeSchoolFile(file) {
  if (!file || !(/\.(xlsx|csv)$/i).test(file.name) || file.size > 720 * 1024)
    throw new Error('请选择不超过 720 KiB 的 .xlsx 或 .csv 文件。');
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({ filename: file.name, content: String(reader.result).split(',')[1] });
    reader.onerror = () => reject(new Error('文件读取失败。'));
    reader.readAsDataURL(file);
  });
}
