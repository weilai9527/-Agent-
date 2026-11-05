import React, { useEffect, useRef, useState } from 'react';
import { clipMessage, confirmPendingVideo, fetchQuestionClip, questionRecorder } from './questionMedia.js';
import './questionMedia.css';

export default function QuestionMedia({ interviewId, questionId, request, beforeLeaveRef, disabled = false }) {
  const preview = useRef(null);
  const session = useRef(null);
  const [view, setView] = useState({ state: 'idle', message: '' });

  useEffect(() => {
    const room = { recorder: null, continueText: false };
    session.current = room;
    setView({ state: 'idle', message: '' });

    // 提交答案、切到语音及结束面试均通过这个钩子先关闭本题摄像头。
    const finish = async ({ requireConfirmed = false } = {}) => {
      if (requireConfirmed || !room.continueText) await room.recorder?.stop();
      if (requireConfirmed) await confirmPendingVideo(request, interviewId);
    };
    beforeLeaveRef.current = finish;
    const onPageHide = () => { room.recorder?.stop().catch(() => {}); };
    window.addEventListener('pagehide', onPageHide);
    return () => {
      window.removeEventListener('pagehide', onPageHide);
      if (beforeLeaveRef.current === finish) beforeLeaveRef.current = null;
      session.current = null;
      onPageHide();
    };
  }, [interviewId, questionId, beforeLeaveRef, request]);

  if (!questionId) return null;
  function record() {
    const room = session.current;
    if (disabled || !room || room.recorder) return;
    room.continueText = false;
    room.recorder = questionRecorder({
      request, interviewId, questionId, preview: preview.current,
      onState(state, message) {
        if (session.current !== room) return;
        setView({ state, message });
        if (state === 'idle') room.recorder = null;
      },
    });
    room.recorder.start().catch(() => {});
  }
  return (
    <section className="question-media" aria-label="本题视频录制">
      <strong>本题视频录制</strong>
      <p>可选。开启后会发布摄像头画面并申请云录制；文字回答仍需点击发送。</p>
      <div className="question-media-preview" ref={preview} />
      <div className="question-media-actions">
        {view.state === 'idle' && <button type="button" disabled={disabled} onClick={record}>开启摄像头并录制本题</button>}
        {['opening', 'recording', 'unconfirmed'].includes(view.state) && (
          <button type="button" onClick={() => session.current?.recorder?.stop().catch(() => {})}>
            {view.state === 'unconfirmed' ? '重试确认停录' : '关闭摄像头并停止录制'}
          </button>
        )}
        {view.state === 'unconfirmed' && <button type="button" onClick={() => {
          session.current.continueText = true;
          setView({ state: 'unconfirmed', message: '可继续文字作答。摄像头已关闭，云端停录仍待确认。' });
        }}>继续文字作答</button>}
      </div>
      <span role="status">{view.message}</span>
    </section>
  );
}

export function QuestionPlayback({ interviewId, questionId, request }) {
  const [clip, setClip] = useState(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const attempt = useRef(0);
  useEffect(() => {
    setClip(null);
    setNote('');
    setBusy(false);
    return () => { attempt.current++; };
  }, [interviewId, questionId]);

  useEffect(() => {
    if (!clip) return;
    const timer = setTimeout(() => {
      setClip(null);
      setNote('回放授权已过期，可重新获取。');
    }, Math.max(0, clip.expiresAt - Date.now()));
    return () => clearTimeout(timer);
  }, [clip]);

  async function load() {
    const current = ++attempt.current;
    setBusy(true);
    setNote('');
    try {
      // 点播才申请本题的短期播放授权，不把签名链接写进报告或浏览器存储。
      const result = await fetchQuestionClip(request, interviewId, questionId);
      if (attempt.current === current) setClip(result);
    } catch (error) {
      if (attempt.current === current) setNote(clipMessage(error, true));
    } finally {
      if (attempt.current === current) setBusy(false);
    }
  }
  if (!questionId) return null;
  return (
    <div className="question-media question-media-playback">
      {clip ? <video controls playsInline preload="metadata" src={clip.url} onError={() => {
        setClip(null);
        setNote('片段暂时无法播放，请重新获取回放。');
      }} /> : <button type="button" disabled={busy} onClick={load}>{busy ? '正在获取片段…' : '查看本题录像'}</button>}
      <span role="status">{note}</span>
    </div>
  );
}
