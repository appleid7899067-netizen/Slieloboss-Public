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
  openai: { label: 'OpenAI', models: ['gpt-4o-mini', 'gpt-4.1-mini'], reasoning: { supported: false, options: [] } },
  gemini: { label: 'Gemini', models: ['gemini-3-flash-preview'], reasoning: { supported: false, options: [] } },
  qwen: { label: 'Qwen', models: ['qwen3.5-plus'], reasoning },
  custom: { label: { zh: '自定义', en: 'Custom' }, models: [], reasoning }
};

// Vercel functions are stateless. Keep non-secret configuration in a small
// browser cookie so POST /config survives the immediate GET /config refresh
// performed by the settings UI. API keys/passwords are intentionally excluded.
const COOKIE_KEY = 'cowagent_vercel_config';
const PERSISTED_KEYS = new Set([
  'model',
  'bot_type',
  'use_linkai',
  'enable_thinking',
  'reasoning_effort',
  'reasoning_effort_by_model',
  'subagent_enabled',
  'self_evolution_enabled',
  'agent_max_context_tokens',
  'agent_max_context_turns',
  'agent_max_steps',
  'agent_permission_mode',
  'cow_lang'
]);

function parseCookies(header) {
  const out = {};
  String(header || '').split(';').forEach(part => {
    const i = part.indexOf('=');
    if (i < 0) return;
    const key = part.slice(0, i).trim();
    const value = part.slice(i + 1).trim();
    if (key) out[key] = value;
  });
  return out;
}

function readOverrides(req) {
  try {
    const raw = parseCookies(req.headers?.cookie)[COOKIE_KEY];
    return raw ? JSON.parse(decodeURIComponent(raw)) : {};
  } catch {
    return {};
  }
}

function sanitizeUpdates(updates) {
  if (!updates || typeof updates !== 'object' || Array.isArray(updates)) return {};
  const safe = {};
  for (const [key, value] of Object.entries(updates)) {
    if (PERSISTED_KEYS.has(key)) safe[key] = value;
  }
  return safe;
}

function responseBody(req) {
  const overrides = readOverrides(req);
  return {
    status: 'success',
    use_agent: true,
    title: 'CowAgent',
    model: overrides.model || 'deepseek-v4-flash',
    bot_type: overrides.bot_type || 'deepseek',
    use_linkai: overrides.use_linkai ?? false,
    enable_thinking: overrides.enable_thinking ?? true,
    reasoning_effort: overrides.reasoning_effort || 'medium',
    reasoning_effort_by_model: overrides.reasoning_effort_by_model || {},
    subagent_enabled: overrides.subagent_enabled ?? true,
    self_evolution_enabled: overrides.self_evolution_enabled ?? false,
    agent_permission_mode: overrides.agent_permission_mode || 'workspace-write',
    permission_modes: ['read-only', 'workspace-write', 'full-access'],
    api_bases: {},
    api_keys: {},
    providers,
    ...(overrides.agent_max_context_tokens != null ? { agent_max_context_tokens: overrides.agent_max_context_tokens } : {}),
    ...(overrides.agent_max_context_turns != null ? { agent_max_context_turns: overrides.agent_max_context_turns } : {}),
    ...(overrides.agent_max_steps != null ? { agent_max_steps: overrides.agent_max_steps } : {})
  };
}

module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');

  if (req.method === 'GET') return res.status(200).json(responseBody(req));

  if (req.method === 'POST') {
    const updates = sanitizeUpdates(req.body?.updates);
    const current = readOverrides(req);
    const merged = { ...current, ...updates };
    const encoded = encodeURIComponent(JSON.stringify(merged));

    // Stay below typical browser cookie limits. If a large per-model map is
    // submitted, the request still succeeds; only persistence is skipped.
    if (encoded.length <= 3800) {
      res.setHeader(
        'Set-Cookie',
        `${COOKIE_KEY}=${encoded}; Path=/; Max-Age=2592000; SameSite=Lax`
      );
    }

    return res.status(200).json({ status: 'success', applied: req.body?.updates || {} });
  }

  return res.status(405).json({ status: 'error', message: 'Method not allowed' });
};
