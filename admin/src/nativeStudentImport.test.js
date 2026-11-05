import assert from 'node:assert/strict';
import test from 'node:test';
import { readStudentTsv } from './nativeStudentImport.js';

test('TSV can be staged without sending passwords or exposing them in errors', async () => {
  const blob = body => new Blob(['\uFEFF学号\t姓名\t临时密码\r\n', body]);
  const row = 'a_1\t示例学生\tLocalTestSecret!12';
  assert.deepEqual(await readStudentTsv(blob(row+'\r\n')), [
    {student_no:'A_1',name:'示例学生',temporary_password:'LocalTestSecret!12'},
  ]);
  await assert.rejects(() => readStudentTsv(blob(row+'\n'+row)), /第 3 行的学号.*重复/);
  await assert.rejects(() => readStudentTsv(blob('x\t无效\tLocalTestSecret!12')), error =>
    /第 2 行/.test(error.message) && !error.message.includes('LocalTestSecret'));
});
