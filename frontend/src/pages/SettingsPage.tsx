import { useState, useEffect, useRef } from 'react';
import { getSettings, updateSettings, getAppSettings, updateAppSettings, type LLMSettings } from '@/services/api';

const LLM_PROVIDERS = [
  { provider: 'DeepSeek', api_key: 'sk-...', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['deepseek-v3.2'] },
  { provider: 'Qwen', api_key: 'sk-...', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['qwen3.5-plus', 'qwen3.5-flash', 'qwen3-max-2026-01-23'] },
  { provider: 'Kimi', api_key: 'sk-...', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['kimi-k2.5'] },
  { provider: 'MiniMax', api_key: 'eyJ...', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['MiniMax-M2.1'] },
];

const defaultSettings: LLMSettings = {
  provider: 'DeepSeek',
  base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  api_key: '',
  model: 'deepseek-v3.2',
};

function getProviderConfig(providerName: string) {
  return LLM_PROVIDERS.find((p) => p.provider === providerName);
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<LLMSettings>(defaultSettings);
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  // Track whether the server has an API key stored
  const [hasApiKey, setHasApiKey] = useState(false);
  // Track whether the user is actively editing the API key field
  const [isEditingKey, setIsEditingKey] = useState(false);

  // CBETA settings
  const [cbetaMaxResults, setCbetaMaxResults] = useState(20);
  const [cbetaSaving, setCbetaSaving] = useState(false);
  const [cbetaSaved, setCbetaSaved] = useState(false);
  const [cbetaError, setCbetaError] = useState('');
  const cbetaDebounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Thinking mode settings
  const [enableThinking, setEnableThinking] = useState(false);
  const [thinkingSaving, setThinkingSaving] = useState(false);
  const [thinkingSaved, setThinkingSaved] = useState(false);
  const [thinkingError, setThinkingError] = useState('');

  useEffect(() => {
    getSettings()
      .then((data) => {
        setSettings(data);
        setHasApiKey(data.has_api_key ?? false);
      })
      .catch(() => {
        // Use defaults if settings not available yet
      });
    getAppSettings()
      .then((data) => {
        setCbetaMaxResults(data.cbeta_max_results);
        setEnableThinking(data.enable_thinking);
      })
      .catch(() => {
        // Use defaults
      });
  }, []);

  const handleProviderChange = (newProvider: string) => {
    const config = getProviderConfig(newProvider);
    if (config) {
      setSettings((prev) => ({
        ...prev,
        provider: newProvider,
        base_url: config.base_url,
        model: config.models[0] ?? '',
      }));
    } else {
      setSettings((prev) => ({ ...prev, provider: newProvider }));
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    setError('');
    setSaved(false);
    try {
      const result = await updateSettings(settings);
      setSettings(result);
      setHasApiKey(result.has_api_key ?? false);
      setIsEditingKey(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch {
      setError('保存失败，请重试。');
    } finally {
      setIsSaving(false);
    }
  };

  const currentConfig = getProviderConfig(settings.provider);
  const models = currentConfig?.models ?? [];
  const keyPlaceholder = currentConfig?.api_key ?? 'sk-...';

  const handleCbetaChange = (value: number) => {
    const clamped = Math.min(100, Math.max(5, value));
    setCbetaMaxResults(clamped);
    setCbetaSaved(false);
    setCbetaError('');

    if (cbetaDebounceRef.current) clearTimeout(cbetaDebounceRef.current);
    cbetaDebounceRef.current = setTimeout(async () => {
      setCbetaSaving(true);
      try {
        const result = await updateAppSettings({ cbeta_max_results: clamped });
        setCbetaMaxResults(result.cbeta_max_results);
        setCbetaSaved(true);
        setTimeout(() => setCbetaSaved(false), 3000);
      } catch {
        setCbetaError('保存失败，请重试。');
      } finally {
        setCbetaSaving(false);
      }
    }, 600);
  };

  const handleThinkingToggle = async (enabled: boolean) => {
    setEnableThinking(enabled);
    setThinkingSaved(false);
    setThinkingError('');
    setThinkingSaving(true);
    try {
      const result = await updateAppSettings({ enable_thinking: enabled });
      setEnableThinking(result.enable_thinking);
      setThinkingSaved(true);
      setTimeout(() => setThinkingSaved(false), 3000);
    } catch {
      setEnableThinking(!enabled);
      setThinkingError('保存失败，请重试。');
    } finally {
      setThinkingSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-xl p-6">
      <h1 className="mb-6 font-serif text-2xl font-semibold text-ink-800">设置</h1>

      <div className="rounded-lg border border-parchment-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 font-serif text-lg font-medium text-ink-800">LLM 服务配置</h2>

        <div className="space-y-4">
          {/* Provider */}
          <div>
            <label className="mb-1 block text-sm text-ink-700">服务提供商</label>
            <select
              value={settings.provider}
              onChange={(e) => handleProviderChange(e.target.value)}
              className="w-full rounded-md border border-parchment-200 bg-parchment-50 px-3 py-2 text-sm text-ink-800 focus:border-cinnabar-400 focus:outline-none focus:ring-1 focus:ring-cinnabar-400"
            >
              {LLM_PROVIDERS.map((p) => (
                <option key={p.provider} value={p.provider}>
                  {p.provider}
                </option>
              ))}
            </select>
          </div>

          {/* Base URL */}
          <div>
            <label className="mb-1 block text-sm text-ink-700">Base URL</label>
            <input
              type="url"
              value={settings.base_url}
              onChange={(e) => setSettings({ ...settings, base_url: e.target.value })}
              placeholder={currentConfig?.base_url ?? 'https://dashscope.aliyuncs.com/compatible-mode/v1'}
              className="w-full rounded-md border border-parchment-200 bg-parchment-50 px-3 py-2 text-sm text-ink-800 placeholder:text-parchment-400 focus:border-cinnabar-400 focus:outline-none focus:ring-1 focus:ring-cinnabar-400"
            />
          </div>

          {/* API Key */}
          <div>
            <label className="mb-1 block text-sm text-ink-700">API Key</label>
            {!isEditingKey && hasApiKey ? (
              <div className="flex items-center gap-2">
                <div className="flex-1 rounded-md border border-parchment-200 bg-parchment-50 px-3 py-2 text-sm text-parchment-400">
                  ••••••••••••
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setIsEditingKey(true);
                    setSettings({ ...settings, api_key: '' });
                  }}
                  className="rounded-md border border-parchment-200 px-3 py-2 text-sm text-ink-700 transition-colors hover:bg-parchment-100"
                >
                  修改
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <input
                  type="password"
                  value={settings.api_key}
                  onChange={(e) => setSettings({ ...settings, api_key: e.target.value })}
                  placeholder={keyPlaceholder}
                  className="flex-1 rounded-md border border-parchment-200 bg-parchment-50 px-3 py-2 text-sm text-ink-800 placeholder:text-parchment-400 focus:border-cinnabar-400 focus:outline-none focus:ring-1 focus:ring-cinnabar-400"
                />
                {isEditingKey && hasApiKey && (
                  <button
                    type="button"
                    onClick={() => {
                      setIsEditingKey(false);
                      setSettings({ ...settings, api_key: '' });
                    }}
                    className="rounded-md border border-parchment-200 px-3 py-2 text-sm text-parchment-400 transition-colors hover:bg-parchment-100"
                  >
                    取消
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Model */}
          <div>
            <label className="mb-1 block text-sm text-ink-700">模型名称</label>
            {models.length > 0 ? (
              <select
                value={settings.model}
                onChange={(e) => setSettings({ ...settings, model: e.target.value })}
                className="w-full rounded-md border border-parchment-200 bg-parchment-50 px-3 py-2 text-sm text-ink-800 focus:border-cinnabar-400 focus:outline-none focus:ring-1 focus:ring-cinnabar-400"
              >
                {models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={settings.model}
                onChange={(e) => setSettings({ ...settings, model: e.target.value })}
                placeholder="模型名称"
                className="w-full rounded-md border border-parchment-200 bg-parchment-50 px-3 py-2 text-sm text-ink-800 placeholder:text-parchment-400 focus:border-cinnabar-400 focus:outline-none focus:ring-1 focus:ring-cinnabar-400"
              />
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="mt-6 flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="rounded-md bg-cinnabar-500 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-cinnabar-600 disabled:opacity-50"
          >
            {isSaving ? '保存中...' : '保存设置'}
          </button>
          {saved && <span className="text-sm text-green-600">已保存</span>}
          {error && <span className="text-sm text-red-500">{error}</span>}
        </div>
      </div>

      {/* CBETA Settings */}
      <div className="mt-6 rounded-lg border border-parchment-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 font-serif text-lg font-medium text-ink-800">CBETA 检索设置</h2>

        <div>
          <label className="mb-1 block text-sm text-ink-700">CBETA 检索条目数量</label>
          <p className="mb-3 text-xs text-parchment-400">
            设置每次检索 CBETA 线上佛典时返回的最大条目数量。数值越大，检索结果越全面，但耗时也越长。
          </p>
          <div className="flex items-center gap-3">
            <input
              type="number"
              min={5}
              max={100}
              value={cbetaMaxResults}
              onChange={(e) => handleCbetaChange(Number(e.target.value))}
              className="w-24 rounded-md border border-parchment-200 bg-parchment-50 px-3 py-2 text-sm text-ink-800 focus:border-cinnabar-400 focus:outline-none focus:ring-1 focus:ring-cinnabar-400"
            />
            <span className="text-xs text-parchment-400">范围：5 - 100</span>
            {cbetaSaving && <span className="text-xs text-parchment-400">保存中...</span>}
            {cbetaSaved && <span className="text-xs text-green-600">已保存</span>}
            {cbetaError && <span className="text-xs text-red-500">{cbetaError}</span>}
          </div>
        </div>
      </div>
      {/* AI Thinking Mode */}
      <div className="mt-6 rounded-lg border border-parchment-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 font-serif text-lg font-medium text-ink-800">AI 思考模式</h2>

        <div>
          <p className="mb-3 text-xs text-parchment-400">
            开启后 AI 助手会进行深度思考再回答，回复质量更高但耗时更长。
          </p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              role="switch"
              aria-checked={enableThinking}
              onClick={() => handleThinkingToggle(!enableThinking)}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-cinnabar-400/20 ${
                enableThinking ? 'bg-cinnabar-500' : 'bg-parchment-300'
              }`}
            >
              <span
                className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform ${
                  enableThinking ? 'translate-x-5' : 'translate-x-0'
                }`}
              />
            </button>
            <span className="text-sm text-ink-700">{enableThinking ? '已开启' : '已关闭'}</span>
            {thinkingSaving && <span className="text-xs text-parchment-400">保存中...</span>}
            {thinkingSaved && <span className="text-xs text-green-600">已保存</span>}
            {thinkingError && <span className="text-xs text-red-500">{thinkingError}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
