const models = [
  'deepseek-v4-flash',
  'deepseek-v4-pro',
  'deepseek-chat',
  'openrouter/free',
  'qwen3.5-plus',
  'gpt-4o-mini',
  'gemini-3-flash-preview'
];

const reasoning = {
  supported: true,
  param: 'reasoning_effort',
  default: 'medium',
  options: [
    { value: 'low', label: 'Low' },
    { value: 'medium', label: 'Medium' },
    { value: 'high', label: 'High' },
    { value: 'xhigh', label: 'XHigh' },
    { value: 'max', label: 'Max' }
  ]
};

const providers = {
  deepseek: { label: 'DeepSeek', models, reasoning },
  openrouter: { label: 'OpenRouter', models, reasoning },
  openai: {
    label: 'OpenAI',
    models: ['gpt-4o-mini', 'gpt-4.1-mini'],
    reasoning: { supported: false, options: [] }
  },
  gemini: {
    label: 'Gemini',
    models: ['gemini-3-flash-preview'],
    reasoning: { supported: false, options: [] }
  },
  qwen: { label: 'Qwen', models: ['qwen3.5-plus'], reasoning },
  custom: {
    label: { zh: '自定义', en: 'Custom' },
    models: [],
    reasoning
  }
};

function responseBody() {
  return {
    status: 'success',
    use_agent: true,
    title: 'CowAgent',
    model: 'deepseek-v4-flash',
    bot_type: 'deepseek',
    use_linkai: false,
    enable_thinking: true,
    reasoning_effort: 'medium',
    reasoning_effort_by_model: {},
    subagent_enabled: true,
    self_evolution_enabled: false,
    agent_permission_mode: 'workspace-write',
    permission_modes: ['read-only', 'workspace-write', 'full-access'],
    api_bases: {},
    api_keys: {},
    providers
  };
}

module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');

  if (req.method === 'GET') {
    return res.status(200).json(responseBody());
  }

  if (req.method === 'POST') {
    return res.status(200).json({
      status: 'success',
      applied: req.body?.updates || {}
    });
  }

  return res.status(405).json({ status: 'error', message: 'Method not allowed' });
};
