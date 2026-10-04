/* 智能体对话：SSE 流式渲染 + 工具调用卡片。后端无状态，历史由前端持有。 */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const messagesEl = $('agent-messages');
  const form = $('agent-form');
  const input = $('agent-text');
  const sendBtn = $('agent-send');
  const notice = $('agent-notice');

  /* 会话历史：前端持有，每轮全量上送（OpenAI 消息格式） */
  let history = [];

  /* 渲染：气泡 */
  function addBubble(role, text) {
    const b = document.createElement('div');
    b.className = 'msg ' + (role === 'user' ? 'msg-user' : 'msg-bot');
    b.textContent = text;
    messagesEl.appendChild(b);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return b;
  }

  /* 工具卡片：一行式 */
  function addToolCard(name, args) {
    const card = document.createElement('div');
    card.className = 'agent-card';
    card.textContent = '工具 ' + name + ' ' + JSON.stringify(args);
    messagesEl.appendChild(card);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return card;
  }

  /* busy 状态：禁用输入 */
  function setBusy(busy) {
    sendBtn.disabled = busy;
    input.disabled = busy;
  }

  let cur = null;
  let turnTools = [];    // 本轮工具消息缓冲：tool_call 累积、tool_result 补全

  function handleEvent(e) {
    if (e.type === 'delta') {
      if (!cur) cur = addBubble('bot', '');
      cur.textContent += e.text;
      messagesEl.scrollTop = messagesEl.scrollHeight;
    } else if (e.type === 'tool_call') {
      turnTools.push({ id: 'h' + turnTools.length, name: e.name, args: e.args });
      addToolCard(e.name, e.args);
      cur = null;
    } else if (e.type === 'tool_result') {
      const last = turnTools[turnTools.length - 1];
      if (last) last.summary = e.summary;
      const card = addToolCard(e.name + ' 结果', { summary: e.summary });
      if (e.summary.indexOf('[pending]') >= 0) card.classList.add('agent-card-pending');
      cur = null;
    } else if (e.type === 'done') {
      if (!cur) addBubble('bot', '（本轮完成）');
      cur = null;
    }
  }

  async function send(text) {
    addBubble('user', text);
    history.push({ role: 'user', content: text });
    setBusy(true);
    try {
      const resp = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: history })
      });
      if (!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status);
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const r = await reader.read();
        if (r.done) break;
        buf += dec.decode(r.value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();
        for (const line of lines) {
          const t = line.trim();
          if (t.indexOf('data: ') === 0) handleEvent(JSON.parse(t.slice(6)));
        }
      }
      /* 历史回传：assistant 文本 + tool_calls + tool 摘要（OpenAI 消息格式） */
      const botText = cur ? cur.textContent : '';
      if (turnTools.length) {
        history.push({
          role: 'assistant', content: botText,
          tool_calls: turnTools.map((t) => ({
            id: t.id, type: 'function',
            function: { name: t.name, arguments: JSON.stringify(t.args) }
          }))
        });
        for (const t of turnTools) {
          history.push({ role: 'tool', tool_call_id: t.id, content: t.summary });
        }
      } else {
        history.push({ role: 'assistant', content: botText });
      }
    } catch (err) {
      addBubble('bot', '对话失败：' + err.message);
    } finally {
      setBusy(false);
      cur = null;
      turnTools = [];
    }
  }

  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    send(text);
  });

  /* 演示模式提示条：由后端 status 端点告知 mock/真实 */
  fetch('/api/agent/status').then((r) => r.json()).then((s) => {
    if (notice && s.mock) notice.hidden = false;
  }).catch(() => {});
  const dismiss = document.getElementById('agent-notice-dismiss');
  if (dismiss) dismiss.addEventListener('click', () => { notice.hidden = true; });
})();
