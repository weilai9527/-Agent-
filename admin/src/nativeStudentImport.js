// 在本地解析导入文件，与手工录入共用校验规则和 JSON 格式，再提交给网关。
// 报错时不要回显文件中的整行数据或密码。
export async function readStudentTsv(file) {
  if (file.size > 256 * 1024) throw new Error('名单文件须小于等于 256 KB。');
  const lines = (await file.text()).replace(/^\uFEFF/, '').split(/\r\n|\n|\r/);
  while (lines.length && !lines.at(-1).length) lines.pop();
  const header = lines.shift();
  if (!['学号\t姓名\t临时密码', 'student_no\tname\ttemporary_password'].includes(header))
    throw new Error('名单首行须为学号、姓名、临时密码，字段之间使用制表符。');
  if (!lines.length || lines.length > 100) throw new Error('每个文件须包含 1 至 100 位学生。');
  const numbers = new Set();
  return lines.map((line, index) => {
    const fields = line.split('\t');
    const number = fields[0]?.trim().toUpperCase();
    const name = fields[1]?.trim();
    const password = fields[2];
    if (fields.length !== 3 || !/^[A-Z0-9_-]{3,40}$/.test(number) || !name || name.length > 120
        || !password || password.length < 8 || password.length > 256)
      throw new Error(`第 ${index + 2} 行的学号、姓名或临时密码格式有误。`);
    if (numbers.has(number)) throw new Error(`第 ${index + 2} 行的学号在本次导入中重复。`);
    numbers.add(number);
    return { student_no: number, name, temporary_password: password };
  });
}
