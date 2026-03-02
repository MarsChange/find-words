import { useState, useEffect } from 'react';
import { getSettings, updateSettings, type LLMSettings } from '@/services/api';

const LLM_PROVIDERS = [
  { provider: 'DeepSeek', api_key: 'sk-...', base_url: 'https://api.deepseek.com/v1', models: ['deepseek-reasoner', 'deepseek-chat'] },
  { provider: 'Qwen', api_key: 'sk-...', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['qwen3.5-plus', 'qwen3.5-flash'] },
  { provider: 'Kimi', api_key: 'sk-...', base_url: 'https://api.moonshot.cn/v1', models: ['kimi-k2.5'] },
  { provider: 'MiniMax', api_key: 'eyJ...', base_url: 'https://api.minimax.com/v1', models: ['MiniMax-M2.5'] },
];

const defaultSettings: LLMSettings = {
  provider: 'DeepSeek',
  base_url: 'https://api.deepseek.com/v1',
  api_key: '',
  model: 'deepseek-reasoner',
};

function getProviderConfig(providerName: string) {
  return LLM_PROVIDERS.find((p) => p.provider === providerName);
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<LLMSettings>(defaultSettings);
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    getSettings()
      .then(setSettings)
      .catch(() => {
        // Use defaults if settings not available yet
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
              placeholder={currentConfig?.base_url ?? 'https://api.deepseek.com/v1'}
              className="w-full rounded-md border border-parchment-200 bg-parchment-50 px-3 py-2 text-sm text-ink-800 placeholder:text-parchment-400 focus:border-cinnabar-400 focus:outline-none focus:ring-1 focus:ring-cinnabar-400"
            />
          </div>

          {/* API Key */}
          <div>
            <label className="mb-1 block text-sm text-ink-700">API Key</label>
            <input
              type="password"
              value={settings.api_key}
              onChange={(e) => setSettings({ ...settings, api_key: e.target.value })}
              placeholder={keyPlaceholder}
              className="w-full rounded-md border border-parchment-200 bg-parchment-50 px-3 py-2 text-sm text-ink-800 placeholder:text-parchment-400 focus:border-cinnabar-400 focus:outline-none focus:ring-1 focus:ring-cinnabar-400"
            />
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
    </div>
  );
}
