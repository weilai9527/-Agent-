import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ArrowUp,
  Bot,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Mic2,
  Mic,
  MicOff,
  Plus,
  PhoneOff,
  Quote,
  Radio,
  Send,
  Settings,
  ShieldCheck,
  UserRound,
  Volume2,
  VolumeX,
} from 'lucide-react';
import './candidate-room-prototype.css';

const agents = [
  {
    id: 'tech',
    name: '技术一面 Agent',
    shortName: '技术一面',
    role: '项目深挖与核心技术基础',
    question: '在核心项目中，你负责解决了哪些业务问题？能否详细描述一下你的技术方案和个人职责？',
  },
  {
    id: 'arch',
    name: '架构二面 Agent',
    shortName: '架构二面',
    role: '系统设计、工程权衡与稳定性',
    question: '如果这个方案要支撑十倍流量，你会优先改造哪些部分？为什么？',
  },
  {
    id: 'hr',
    name: 'HR Agent',
    shortName: 'HR 面',
    role: '职业动机、协作方式与岗位匹配',
    question: '你为什么考虑这个机会？你希望下一份工作给你带来怎样的成长？',
  },
];

const phaseCopy = {
  connecting: {
    title: '面试官正在接入',
    helper: '请稍等，下一位面试官即将开始。',
  },
  asking: {
    title: '面试官正在提问',
    helper: '你可以先听完问题，也可以在下方记录思路。',
  },
  answering: {
    title: '请回答',
    helper: '语音和文字可以同时使用，系统会合并为本轮回答。',
  },
  thinking: {
    title: '正在整理你的回答',
    helper: '系统正在生成追问或阶段反馈。',
  },
  switching: {
    title: '正在切换面试官',
    helper: '当前阶段已完成，下一位面试官马上开始。',
  },
  feedback: {
    title: '阶段反馈已生成',
    helper: '你可以看完反馈后继续下一阶段。',
  },
  finished: {
    title: '本次模拟面试已完成',
    helper: '完整报告将在后台汇总本次所有阶段表现。',
  },
};

const initialMessages = [
  {
    id: 1,
    speaker: '技术一面 Agent',
    type: 'agent',
    time: '05:42',
    text: '在核心项目中，你负责解决了哪些业务问题？能否详细描述一下你的技术方案和个人职责？',
  },
];

function getAgentStatus(index, currentIndex, phase) {
  if (index < currentIndex) return 'done';
  if (index > currentIndex) return 'upcoming';
  if (phase === 'finished') return 'done';
  return 'active';
}

function renderQuestion(question) {
  const splitPoint = question.indexOf('能否');

  if (splitPoint === -1) return question;

  return (
    <>
      <span className="question-line question-line--quiet">{question.slice(0, splitPoint)}</span>
      <span className="question-line">{question.slice(splitPoint)}</span>
    </>
  );
}

function CandidateRoomPrototype() {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [phase, setPhase] = useState('answering');
  const [micOn, setMicOn] = useState(true);
  const [recording, setRecording] = useState(false);
  const [speakerOn, setSpeakerOn] = useState(true);
  const [answerMode, setAnswerMode] = useState('voice');
  const [typedText, setTypedText] = useState('');
  const [speechDraft, setSpeechDraft] = useState('我主要负责性能治理和核心链路稳定性，先从业务指标定位问题，再拆到接口、渲染和资源加载三个方向。');
  const [messages, setMessages] = useState(initialMessages);
  const [feedbackVisible, setFeedbackVisible] = useState(false);

  const currentAgent = agents[currentIndex] || agents[agents.length - 1];
  const phaseInfo = phaseCopy[phase];
  const canAnswer = phase === 'answering';
  const answerStatusLabel = canAnswer
    ? answerMode === 'voice'
      ? recording
        ? '正在收音'
        : '使用语音回答'
      : '使用文字回答'
    : phase === 'finished'
      ? '面试已结束'
      : '等待下一阶段';

  const submitAnswer = () => {
    if (!canAnswer) return;

    const normalizedText = typedText.trim();
    const normalizedSpeech = speechDraft.trim();
    const activeAnswer = answerMode === 'voice' ? normalizedSpeech : normalizedText;

    if (!activeAnswer) return;

    const sourceLabel = answerMode === 'voice' ? '语音' : '文字';

    setMessages((current) => [
      ...current,
      {
        id: Date.now(),
        speaker: '候选人',
        type: 'candidate',
        time: '05:44',
        source: sourceLabel,
        text: activeAnswer,
      },
    ]);
    setTypedText('');
    setSpeechDraft('');
    setRecording(false);
    setPhase('thinking');
    window.setTimeout(() => {
      setFeedbackVisible(true);
      setPhase('feedback');
    }, 350);
  };

  const continueInterview = () => {
    setFeedbackVisible(false);

    if (currentIndex >= agents.length - 1) {
      setPhase('finished');
      return;
    }

    const nextIndex = currentIndex + 1;
    const nextAgent = agents[nextIndex];
    setPhase('switching');
    window.setTimeout(() => {
      setCurrentIndex(nextIndex);
      setMessages((current) => [
        ...current,
        {
          id: Date.now() + 1,
          speaker: nextAgent.name,
          type: 'agent',
          time: '05:46',
          text: nextAgent.question,
        },
      ]);
      setPhase('answering');
    }, 450);
  };

  return (
    <main className="candidate-room">
      <aside className="call-pane" aria-label="面试导航">
        <div className="brand-block">
          <strong>LightHire</strong>
          <span>AI 面试平台</span>
        </div>

        <section className="side-section" aria-label="面试流程">
          <div className="timeline-steps">
            {agents.map((agent, index) => {
              const status = getAgentStatus(index, currentIndex, phase);
              return (
                <div className={`timeline-step ${status}`} key={agent.id}>
                  <div className="timeline-dot">
                    {status === 'done' ? <Check size={15} /> : index + 1}
                  </div>
                  <div>
                    <strong>{agent.shortName}</strong>
                    <span>{status === 'done' ? '已完成' : status === 'active' ? currentAgent.role : '即将开始'}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <button className="new-session-button" type="button">
          <Plus size={17} />
          <span>新建面试</span>
        </button>

        <div className="candidate-profile">
          <div className="profile-avatar">N</div>
          <div>
            <strong>你好，Nico</strong>
            <span>候选人</span>
          </div>
          <ChevronRight size={16} />
        </div>
      </aside>

      <section className="work-pane" aria-label="AI 面试空间">
        <header className="room-header">
          <div>
            <span>AI 面试空间</span>
            <strong>你好，Nico · {currentAgent.role}</strong>
          </div>
          <div className="security-status">
            <ShieldCheck size={17} />
            <span>数据安全保护中</span>
            <i />
            <button className="settings-button" type="button" aria-label="设置" title="设置">
              <Settings size={16} />
            </button>
          </div>
        </header>

        <section className="hero-question" aria-label="当前问题">
          <span>{currentAgent.shortName}</span>
          <h1>{renderQuestion(currentAgent.question)}</h1>
        </section>

        <section className="agent-listening" aria-label="面试官状态">
          <div className="voice-wave" />
          <div className={`agent-orb ${recording ? 'speaking' : ''}`}>
            <Bot size={36} />
          </div>
          <div className="voice-wave right" />
          <p>{currentAgent.shortName}试官 · {recording ? '正在听你回答' : phaseInfo.title}</p>
        </section>

        <section className="answer-dock" aria-label="候选人回答区">
          <div className="answer-head">
            <div>
              <span>候选人回答</span>
              <strong>{answerStatusLabel}</strong>
            </div>
            <div className="answer-tabs" aria-label="回答方式">
              <button
                className={answerMode === 'voice' ? 'active' : ''}
                type="button"
                disabled={!canAnswer}
                onClick={() => {
                  setAnswerMode('voice');
                  setRecording(micOn && canAnswer);
                }}
              >
                语音回答
              </button>
              <button
                className={answerMode === 'text' ? 'active' : ''}
                type="button"
                disabled={!canAnswer}
                onClick={() => {
                  setAnswerMode('text');
                  setRecording(false);
                }}
              >
                文字回答
              </button>
            </div>
          </div>

          {answerMode === 'voice' ? (
            <div className="voice-mode">
              <div className="voice-listening">
                <span className={recording ? 'pulse-dot active' : 'pulse-dot'} />
                <div>
                  <strong>{recording ? '正在收音...' : '语音未开启'}</strong>
                  <p>{speechDraft || '开启语音后，实时转写会显示在这里。'}</p>
                </div>
              </div>
              <button
                className="submit-answer"
                type="button"
                disabled={!canAnswer || (!micOn && !recording)}
                onClick={() => {
                  if (!canAnswer) return;
                  setPhase('answering');
                  if (!recording) {
                    if (!micOn) return;
                    setRecording(true);
                    return;
                  }
                  submitAnswer();
                }}
              >
                {recording ? <CheckCircle2 size={18} /> : <ArrowUp size={18} />}
                <span>{canAnswer ? (recording ? '提交' : '开始') : '等待'}</span>
              </button>
            </div>
          ) : (
            <div className="text-mode">
              <textarea
                value={typedText}
                disabled={!canAnswer}
                onChange={(event) => {
                  setTypedText(event.target.value);
                  setPhase('answering');
                }}
                placeholder="请输入你的回答。建议先给结论，再补充项目背景、个人职责和结果指标。"
              />
              <button className="submit-answer" type="button" onClick={submitAnswer} disabled={!canAnswer || !typedText.trim()}>
                <Send size={17} />
                <span>发送</span>
              </button>
            </div>
          )}

        </section>

        <div className="call-controls" aria-label="通话控制">
          <button
            className={`pill-control ${micOn ? 'active' : ''}`}
            type="button"
            onClick={() => {
              setMicOn((value) => !value);
              setRecording((value) => (micOn ? false : value));
            }}
            aria-label={micOn ? '关闭麦克风' : '开启麦克风'}
            title={micOn ? '关闭麦克风' : '开启麦克风'}
          >
            {micOn ? <Mic2 size={17} /> : <MicOff size={17} />}
            <span>麦克风</span>
          </button>
          <button
            className={`pill-control ${speakerOn ? 'active' : ''}`}
            type="button"
            onClick={() => setSpeakerOn((value) => !value)}
            aria-label={speakerOn ? '关闭扬声器' : '开启扬声器'}
            title={speakerOn ? '关闭扬声器' : '开启扬声器'}
          >
            {speakerOn ? <Volume2 size={17} /> : <VolumeX size={17} />}
            <span>扬声器</span>
          </button>
          <button
            className="pill-control danger"
            type="button"
            onClick={() => setPhase('finished')}
            aria-label="结束面试"
            title="结束面试"
          >
            <PhoneOff size={17} />
            <span>挂断</span>
          </button>
          {(phase === 'thinking' || phase === 'feedback') && (
            <button className="pill-control next" type="button" onClick={continueInterview}>
              <span>{phase === 'feedback' ? '进入下一阶段' : '继续下一步'}</span>
              <ChevronRight size={17} />
            </button>
          )}
        </div>
      </section>

      <aside className="insight-pane" aria-label="面试信息">
        <section className="insight-card progress-card">
          <div className="card-kicker">
            <span>当前问题</span>
            <i />
          </div>
          <strong>{currentIndex + 1} / {agents.length}</strong>
          <div className="progress-track">
            <span style={{ width: `${((currentIndex + 1) / agents.length) * 100}%` }} />
          </div>
          <p>{currentAgent.question}</p>
          <button type="button">
            查看追问方向
            <ChevronRight size={15} />
          </button>
        </section>

        <section className="insight-card transcript-card">
          <div className="card-kicker">
            <span>实时记录</span>
            <i />
          </div>
          <div className="quote-mark">
            <Quote size={28} />
          </div>
          <p>面试记录将在对话过程中实时生成，便于你回顾。</p>
          <div className="record-lines">
            {messages.slice(-3).map((message) => (
              <div className="record-line" key={message.id}>
                <span />
                <p>{message.text}</p>
              </div>
            ))}
          </div>
        </section>
      </aside>
    </main>
  );
}

const rootElement = document.getElementById('candidate-room-root');
const appRoot = createRoot(rootElement);
appRoot.render(<CandidateRoomPrototype />);
