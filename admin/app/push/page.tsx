"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/auth";
import AuthGate from "@/components/AuthGate";
import OperatorWsStatus from "@/components/OperatorWsStatus";
import { useOperatorTaskWs } from "@/hooks/useOperatorTaskWs";

interface DeviceToken {
  id: string;
  user_id: string;
  device_token: string;
  platform: string;
  device_info: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

interface PushTestResult {
  success: boolean;
  provider?: string;
  message_id?: string;
  error?: string;
  device_token?: string;
}

export default function PushManagementPage() {
  const [devices, setDevices] = useState<DeviceToken[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedDevice, setSelectedDevice] = useState<DeviceToken | null>(null);
  
  // 推送测试表单
  const [testTitle, setTestTitle] = useState("测试推送");
  const [testBody, setTestBody] = useState("这是一条测试推送消息");
  const [testResult, setTestResult] = useState<PushTestResult | null>(null);
  const [sending, setSending] = useState(false);

  // WebSocket 连接状态
  const { connState, lastAlert, dismissAlert, reconnect } = useOperatorTaskWs({
    operatorId: "system", // 使用系统用户 ID
    enabled: true,
  });

  // 加载设备列表
  const loadDevices = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch<{ devices: DeviceToken[]; count: number }>("/api/v1/device-tokens/devices");
      setDevices(resp.devices || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setDevices([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDevices();
  }, [loadDevices]);

  // 发送测试推送
  const handleTestPush = async () => {
    if (!selectedDevice) {
      setTestResult({ success: false, error: "请先选择设备" });
      return;
    }

    setSending(true);
    setTestResult(null);
    try {
      const resp = await apiFetch<PushTestResult>("/api/v1/device-tokens/test-push", {
        method: "POST",
        body: JSON.stringify({
          device_token: selectedDevice.device_token,
          platform: selectedDevice.platform,
          title: testTitle,
          body: testBody,
          data: { test: true },
        }),
      });
      setTestResult(resp);
    } catch (e) {
      setTestResult({
        success: false,
        error: e instanceof Error ? e.message : String(e),
        device_token: selectedDevice.device_token.substring(0, 20) + "...",
      });
    } finally {
      setSending(false);
    }
  };

  // 删除设备令牌
  const handleDeleteDevice = async (deviceToken: string) => {
    if (!confirm("确定要删除此设备令牌吗？")) return;

    try {
      await apiFetch(`/api/v1/device-tokens/devices/${deviceToken}`, {
        method: "DELETE",
      });
      await loadDevices();
      if (selectedDevice?.device_token === deviceToken) {
        setSelectedDevice(null);
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* Top nav */}
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold text-violet-400">ERIS</span>
          <span className="text-slate-400 text-sm">推送管理</span>
          <nav className="flex items-center gap-1 ml-4">
            <a
              href="/admin"
              className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
            >
              会话
            </a>
            <a
              href="/admin/push"
              className="text-sm text-violet-300 bg-slate-700 px-3 py-1 rounded-md font-medium"
            >
              推送
            </a>
            <a
              href="/admin/scripts"
              className="text-sm text-slate-400 hover:text-white px-3 py-1 rounded-md hover:bg-slate-700 transition"
            >
              话术库
            </a>
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <OperatorWsStatus
            connState={connState}
            lastAlert={lastAlert}
            onDismissAlert={dismissAlert}
            onReconnect={reconnect}
          />
        </div>
      </header>

      {/* Main content */}
      <main className="p-8 max-w-7xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold mb-2">移动端推送管理</h1>
          <p className="text-slate-400 text-sm">
            管理设备令牌和测试推送功能
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* 设备列表 */}
          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">设备列表</h2>
              <button
                onClick={loadDevices}
                className="text-sm text-violet-300 hover:text-white transition"
              >
                刷新
              </button>
            </div>

            {error && (
              <div className="bg-red-900/40 border border-red-700 text-red-200 px-4 py-2 rounded mb-4">
                {error}
              </div>
            )}

            {loading ? (
              <div className="text-center text-slate-400 py-8">加载中...</div>
            ) : devices.length === 0 ? (
              <div className="text-center text-slate-400 py-8">
                暂无设备令牌
              </div>
            ) : (
              <div className="space-y-3 max-h-96 overflow-y-auto">
                {devices.map((device) => (
                  <div
                    key={device.id}
                    className={`p-4 rounded-lg border transition cursor-pointer ${
                      selectedDevice?.id === device.id
                        ? "bg-violet-900/30 border-violet-500"
                        : "bg-slate-900 border-slate-700 hover:border-slate-600"
                    }`}
                    onClick={() => setSelectedDevice(device)}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-medium px-2 py-1 rounded ${
                          device.platform === 'android' 
                            ? 'bg-green-900/40 text-green-300' 
                            : 'bg-blue-900/40 text-blue-300'
                        }`}>
                          {device.platform.toUpperCase()}
                        </span>
                        <span className="text-sm text-slate-300">
                          {device.device_token.substring(0, 20)}...
                        </span>
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteDevice(device.device_token);
                        }}
                        className="text-xs text-red-400 hover:text-red-300 transition"
                      >
                        删除
                      </button>
                    </div>
                    <div className="text-xs text-slate-500">
                      用户 ID: {device.user_id.substring(0, 8)}...
                    </div>
                    <div className="text-xs text-slate-500">
                      更新时间: {new Date(device.updated_at).toLocaleString('zh-CN')}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 推送测试 */}
          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
            <h2 className="text-lg font-semibold mb-4">推送测试</h2>

            {!selectedDevice ? (
              <div className="text-center text-slate-400 py-8">
                请先从左侧选择一个设备
              </div>
            ) : (
              <div className="space-y-4">
                <div>
                  <label className="block text-sm text-slate-300 mb-2">
                    已选择设备
                  </label>
                  <div className="bg-slate-900 rounded-lg p-3 border border-slate-700">
                    <div className="flex items-center gap-2">
                      <span className={`text-xs font-medium px-2 py-1 rounded ${
                        selectedDevice.platform === 'android' 
                          ? 'bg-green-900/40 text-green-300' 
                          : 'bg-blue-900/40 text-blue-300'
                      }`}>
                        {selectedDevice.platform.toUpperCase()}
                      </span>
                      <span className="text-sm text-slate-300">
                        {selectedDevice.device_token}
                      </span>
                    </div>
                  </div>
                </div>

                <div>
                  <label className="block text-sm text-slate-300 mb-2">
                    推送标题
                  </label>
                  <input
                    type="text"
                    value={testTitle}
                    onChange={(e) => setTestTitle(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500"
                    placeholder="输入推送标题"
                  />
                </div>

                <div>
                  <label className="block text-sm text-slate-300 mb-2">
                    推送内容
                  </label>
                  <textarea
                    value={testBody}
                    onChange={(e) => setTestBody(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500"
                    placeholder="输入推送内容"
                    rows={4}
                  />
                </div>

                <button
                  onClick={handleTestPush}
                  disabled={sending}
                  className="w-full bg-violet-600 hover:bg-violet-500 disabled:bg-slate-700 disabled:cursor-not-allowed text-white font-medium py-3 rounded-lg transition"
                >
                  {sending ? "发送中..." : "发送测试推送"}
                </button>

                {testResult && (
                  <div className={`p-4 rounded-lg border ${
                    testResult.success 
                      ? 'bg-green-900/40 border-green-700 text-green-200' 
                      : 'bg-red-900/40 border-red-700 text-red-200'
                  }`}>
                    <div className="font-semibold mb-2">
                      {testResult.success ? "✓ 发送成功" : "✗ 发送失败"}
                    </div>
                    {testResult.provider && (
                      <div className="text-sm">
                        提供商: {testResult.provider}
                      </div>
                    )}
                    {testResult.message_id && (
                      <div className="text-sm">
                        消息 ID: {testResult.message_id}
                      </div>
                    )}
                    {testResult.error && (
                      <div className="text-sm">
                        错误: {testResult.error}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* 配置说明 */}
        <div className="mt-8 bg-slate-800 rounded-xl p-6 border border-slate-700">
          <h2 className="text-lg font-semibold mb-4">配置说明</h2>
          <div className="space-y-4 text-sm text-slate-300">
            <div>
              <h3 className="font-medium text-white mb-2">FCM 配置 (Android)</h3>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>环境变量: <code className="bg-slate-900 px-2 py-1 rounded">FCM_ENABLED=true</code></li>
                <li>凭证文件: <code className="bg-slate-900 px-2 py-1 rounded">FCM_CREDENTIALS_PATH</code></li>
                <li>安装依赖: <code className="bg-slate-900 px-2 py-1 rounded">pip install firebase-admin</code></li>
              </ul>
            </div>
            <div>
              <h3 className="font-medium text-white mb-2">APNs 配置 (iOS)</h3>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>环境变量: <code className="bg-slate-900 px-2 py-1 rounded">APNS_ENABLED=true</code></li>
                <li>Team ID: <code className="bg-slate-900 px-2 py-1 rounded">APNS_TEAM_ID</code></li>
                <li>Key ID: <code className="bg-slate-900 px-2 py-1 rounded">APNS_KEY_ID</code></li>
                <li>Key 路径: <code className="bg-slate-900 px-2 py-1 rounded">APNS_KEY_PATH</code></li>
                <li>Bundle ID: <code className="bg-slate-900 px-2 py-1 rounded">APNS_BUNDLE_ID</code></li>
                <li>安装依赖: <code className="bg-slate-900 px-2 py-1 rounded">pip install httpx</code></li>
              </ul>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}