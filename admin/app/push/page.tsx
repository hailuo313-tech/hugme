"use client";

import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/auth";

interface PushTestRequest {
  user_id: string;
  channel: "android" | "ios";
  device_token: string;
  platform: "android" | "ios";
  notification_type: string;
  payload: {
    title: string;
    body: string;
    [key: string]: any;
  };
}

interface PushResult {
  notification_id: string;
  status: string;
  sent_at: string;
  provider: string;
  message_id?: string;
  error?: string;
}

interface NotificationTask {
  id: string;
  user_id: string;
  channel: string;
  notification_type: string;
  status: string;
  scheduled_at: string;
  sent_at: string | null;
  failure_reason: string | null;
  created_at: string;
}

interface DeviceToken {
  id: string;
  name: string;
  platform: "android" | "ios";
  token: string;
  user_id: string;
  created_at: string;
}

export default function PushManagementPage() {
  const [testRequest, setTestRequest] = useState<PushTestRequest>({
    user_id: "",
    channel: "android",
    device_token: "",
    platform: "android",
    notification_type: "test",
    payload: {
      title: "测试推送",
      body: "这是一条测试推送消息",
    },
  });
  const [result, setResult] = useState<PushResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"test" | "history" | "tokens">("test");
  const [history, setHistory] = useState<NotificationTask[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [deviceTokens, setDeviceTokens] = useState<DeviceToken[]>([]);
  const [showAddToken, setShowAddToken] = useState(false);
  const [newToken, setNewToken] = useState({
    name: "",
    platform: "android" as "android" | "ios",
    token: "",
    user_id: "",
  });

  // 加载推送历史记录
  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const response = await apiFetch<{ items: NotificationTask[] }>(
        "/api/v1/notifications/tasks?limit=20"
      );
      setHistory(response.items || []);
    } catch (e) {
      console.error("Failed to load push history:", e);
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === "history") {
      loadHistory();
    } else if (activeTab === "tokens") {
      loadDeviceTokens();
    }
  }, [activeTab]);

  // 加载设备令牌（从本地存储）
  const loadDeviceTokens = () => {
    try {
      const saved = localStorage.getItem("eris_device_tokens");
      if (saved) {
        setDeviceTokens(JSON.parse(saved));
      }
    } catch (e) {
      console.error("Failed to load device tokens:", e);
    }
  };

  // 保存设备令牌到本地存储
  const saveDeviceTokens = (tokens: DeviceToken[]) => {
    try {
      localStorage.setItem("eris_device_tokens", JSON.stringify(tokens));
      setDeviceTokens(tokens);
    } catch (e) {
      console.error("Failed to save device tokens:", e);
    }
  };

  // 添加设备令牌
  const handleAddToken = () => {
    if (!newToken.name || !newToken.token || !newToken.user_id) {
      alert("请填写所有必填字段");
      return;
    }

    const token: DeviceToken = {
      id: Date.now().toString(),
      name: newToken.name,
      platform: newToken.platform,
      token: newToken.token,
      user_id: newToken.user_id,
      created_at: new Date().toISOString(),
    };

    saveDeviceTokens([...deviceTokens, token]);
    setNewToken({ name: "", platform: "android", token: "", user_id: "" });
    setShowAddToken(false);
  };

  // 删除设备令牌
  const handleDeleteToken = (id: string) => {
    if (confirm("确定要删除这个设备令牌吗？")) {
      saveDeviceTokens(deviceTokens.filter(t => t.id !== id));
    }
  };

  // 使用设备令牌快速填充测试表单
  const handleUseToken = (token: DeviceToken) => {
    setTestRequest({
      ...testRequest,
      platform: token.platform,
      channel: token.platform,
      device_token: token.token,
      user_id: token.user_id,
    });
    setActiveTab("test");
  };

  const handleSendTestPush = async () => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await apiFetch<PushResult>(
        "/api/v1/notifications/send-now",
        {
          method: "POST",
          body: JSON.stringify({
            ...testRequest,
            payload: {
              ...testRequest.payload,
              title: testRequest.payload.title || "测试推送",
              body: testRequest.payload.body || "这是一条测试推送消息",
            },
          }),
        }
      );

      setResult(response);
      
      // 发送成功后重新加载历史
      if (response.status === "sent") {
        loadHistory();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleQuickTest = (platform: "android" | "ios") => {
    const testToken = platform === "android" 
      ? "test_android_token_12345"
      : "test_ios_token_67890";
    
    setTestRequest({
      ...testRequest,
      channel: platform,
      platform: platform,
      device_token: testToken,
      user_id: "test-user-001",
    });
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "sent":
        return "bg-green-900/40 text-green-300 border-green-800";
      case "failed":
        return "bg-red-900/40 text-red-300 border-red-800";
      case "pending":
        return "bg-yellow-900/40 text-yellow-300 border-yellow-800";
      case "sending":
        return "bg-blue-900/40 text-blue-300 border-blue-800";
      default:
        return "bg-slate-800 text-slate-400 border-slate-700";
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-white p-8">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-2xl font-bold mb-6">移动端推送管理</h1>
        
        {/* Tab 切换 */}
        <div className="flex gap-2 mb-6">
          <button
            onClick={() => setActiveTab("test")}
            className={`px-4 py-2 rounded-md transition ${
              activeTab === "test"
                ? "bg-violet-600 text-white"
                : "bg-slate-800 text-slate-400 hover:bg-slate-700"
            }`}
          >
            推送测试
          </button>
          <button
            onClick={() => setActiveTab("history")}
            className={`px-4 py-2 rounded-md transition ${
              activeTab === "history"
                ? "bg-violet-600 text-white"
                : "bg-slate-800 text-slate-400 hover:bg-slate-700"
            }`}
          >
            推送历史
          </button>
          <button
            onClick={() => setActiveTab("tokens")}
            className={`px-4 py-2 rounded-md transition ${
              activeTab === "tokens"
                ? "bg-violet-600 text-white"
                : "bg-slate-800 text-slate-400 hover:bg-slate-700"
            }`}
          >
            设备令牌
          </button>
        </div>

        {activeTab === "test" ? (
          /* 推送测试区域 */
          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700 mb-6">
            <h2 className="text-lg font-semibold mb-4">推送测试</h2>
            
            {/* 快速测试按钮 */}
            <div className="flex gap-3 mb-6">
              <button
                onClick={() => handleQuickTest("android")}
                className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-md transition"
              >
                Android 快速测试
              </button>
              <button
                onClick={() => handleQuickTest("ios")}
                className="bg-purple-600 hover:bg-purple-500 text-white px-4 py-2 rounded-md transition"
              >
                iOS 快速测试
              </button>
            </div>

            {/* 详细配置表单 */}
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">平台</label>
                <select
                  value={testRequest.platform}
                  onChange={(e) => setTestRequest({ ...testRequest, platform: e.target.value as "android" | "ios", channel: e.target.value as "android" | "ios" })}
                  className="w-full bg-slate-900 border border-slate-700 rounded-md px-3 py-2 text-slate-200"
                >
                  <option value="android">Android (FCM)</option>
                  <option value="ios">iOS (APNs)</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">设备令牌</label>
                <input
                  type="text"
                  value={testRequest.device_token}
                  onChange={(e) => setTestRequest({ ...testRequest, device_token: e.target.value })}
                  placeholder="输入设备令牌"
                  className="w-full bg-slate-900 border border-slate-700 rounded-md px-3 py-2 text-slate-200 placeholder-slate-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">用户 ID</label>
                <input
                  type="text"
                  value={testRequest.user_id}
                  onChange={(e) => setTestRequest({ ...testRequest, user_id: e.target.value })}
                  placeholder="输入用户 ID"
                  className="w-full bg-slate-900 border border-slate-700 rounded-md px-3 py-2 text-slate-200 placeholder-slate-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">通知标题</label>
                <input
                  type="text"
                  value={testRequest.payload.title}
                  onChange={(e) => setTestRequest({ ...testRequest, payload: { ...testRequest.payload, title: e.target.value } })}
                  placeholder="输入通知标题"
                  className="w-full bg-slate-900 border border-slate-700 rounded-md px-3 py-2 text-slate-200 placeholder-slate-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">通知内容</label>
                <textarea
                  value={testRequest.payload.body}
                  onChange={(e) => setTestRequest({ ...testRequest, payload: { ...testRequest.payload, body: e.target.value } })}
                  placeholder="输入通知内容"
                  rows={3}
                  className="w-full bg-slate-900 border border-slate-700 rounded-md px-3 py-2 text-slate-200 placeholder-slate-500"
                />
              </div>

              <button
                onClick={handleSendTestPush}
                disabled={loading}
                className="bg-green-600 hover:bg-green-500 text-white px-4 py-2 rounded-md transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? "发送中..." : "发送推送"}
              </button>
            </div>

            {/* 错误信息 */}
            {error && (
              <div className="mt-4 bg-red-900/30 border border-red-800 text-red-200 text-sm rounded-md px-4 py-3">
                错误：{error}
              </div>
            )}

            {/* 结果显示 */}
            {result && (
              <div className="mt-4 bg-slate-900/50 border border-slate-700 rounded-md p-4">
                <h3 className="text-sm font-semibold mb-2">推送结果</h3>
                <div className="space-y-1 text-sm">
                  <div><span className="text-slate-400">状态：</span>
                    <span className={result.status === "sent" ? "text-green-400" : "text-red-400"}>
                      {result.status === "sent" ? "成功" : "失败"}
                    </span>
                  </div>
                  <div><span className="text-slate-400">通知 ID：</span>{result.notification_id}</div>
                  <div><span className="text-slate-400">提供商：</span>{result.provider}</div>
                  {result.message_id && (
                    <div><span className="text-slate-400">消息 ID：</span>{result.message_id}</div>
                  )}
                  {result.error && (
                    <div><span className="text-slate-400">错误：</span><span className="text-red-400">{result.error}</span></div>
                  )}
                  <div><span className="text-slate-400">发送时间：</span>{new Date(result.sent_at).toLocaleString()}</div>
                </div>
              </div>
            )}
          </div>
        ) : activeTab === "history" ? (
          /* 推送历史区域 */
          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">推送历史记录</h2>
              <button
                onClick={loadHistory}
                className="text-sm text-slate-400 hover:text-white transition"
              >
                刷新
              </button>
            </div>

            {historyLoading ? (
              <div className="text-center py-8 text-slate-500">加载中...</div>
            ) : history.length === 0 ? (
              <div className="text-center py-8 text-slate-500">暂无推送记录</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-900/50 text-slate-400 text-xs uppercase">
                    <tr>
                      <th className="text-left px-4 py-3 font-medium">通知 ID</th>
                      <th className="text-left px-4 py-3 font-medium">用户 ID</th>
                      <th className="text-left px-4 py-3 font-medium">渠道</th>
                      <th className="text-left px-4 py-3 font-medium">类型</th>
                      <th className="text-left px-4 py-3 font-medium">状态</th>
                      <th className="text-left px-4 py-3 font-medium">发送时间</th>
                      <th className="text-left px-4 py-3 font-medium">失败原因</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/60">
                    {history.map((task) => (
                      <tr key={task.id} className="hover:bg-slate-700/30 transition">
                        <td className="px-4 py-3 font-mono text-xs text-slate-300">
                          {task.id.slice(0, 8)}...
                        </td>
                        <td className="px-4 py-3 text-slate-300">
                          {task.user_id.slice(0, 8)}...
                        </td>
                        <td className="px-4 py-3 text-slate-300">
                          {task.channel}
                        </td>
                        <td className="px-4 py-3 text-slate-300">
                          {task.notification_type}
                        </td>
                        <td className="px-4 py-3">
                          <span className={`inline-block px-2 py-0.5 text-xs rounded-full border ${getStatusColor(task.status)}`}>
                            {task.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-xs">
                          {task.sent_at ? new Date(task.sent_at).toLocaleString() : "—"}
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-xs">
                          {task.failure_reason || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ) : (
          /* 设备令牌管理区域 */
          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">设备令牌管理</h2>
              <button
                onClick={() => setShowAddToken(true)}
                className="bg-violet-600 hover:bg-violet-500 text-white px-3 py-1.5 rounded-md text-sm transition"
              >
                添加令牌
              </button>
            </div>

            {/* 添加令牌表单 */}
            {showAddToken && (
              <div className="mb-6 bg-slate-900/50 rounded-lg p-4 border border-slate-700">
                <h3 className="text-sm font-semibold mb-3">添加设备令牌</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-1">令牌名称</label>
                    <input
                      type="text"
                      value={newToken.name}
                      onChange={(e) => setNewToken({ ...newToken, name: e.target.value })}
                      placeholder="例如：测试 Android 设备"
                      className="w-full bg-slate-900 border border-slate-700 rounded-md px-3 py-2 text-slate-200 placeholder-slate-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">平台</label>
                    <select
                      value={newToken.platform}
                      onChange={(e) => setNewToken({ ...newToken, platform: e.target.value as "android" | "ios" })}
                      className="w-full bg-slate-900 border border-slate-700 rounded-md px-3 py-2 text-slate-200"
                    >
                      <option value="android">Android</option>
                      <option value="ios">iOS</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">设备令牌</label>
                    <input
                      type="text"
                      value={newToken.token}
                      onChange={(e) => setNewToken({ ...newToken, token: e.target.value })}
                      placeholder="输入设备令牌"
                      className="w-full bg-slate-900 border border-slate-700 rounded-md px-3 py-2 text-slate-200 placeholder-slate-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">用户 ID</label>
                    <input
                      type="text"
                      value={newToken.user_id}
                      onChange={(e) => setNewToken({ ...newToken, user_id: e.target.value })}
                      placeholder="输入用户 ID"
                      className="w-full bg-slate-900 border border-slate-700 rounded-md px-3 py-2 text-slate-200 placeholder-slate-500"
                    />
                  </div>
                </div>
                <div className="flex gap-2 mt-4">
                  <button
                    onClick={handleAddToken}
                    className="bg-green-600 hover:bg-green-500 text-white px-4 py-2 rounded-md text-sm transition"
                  >
                    保存
                  </button>
                  <button
                    onClick={() => setShowAddToken(false)}
                    className="bg-slate-700 hover:bg-slate-600 text-white px-4 py-2 rounded-md text-sm transition"
                  >
                    取消
                  </button>
                </div>
              </div>
            )}

            {/* 令牌列表 */}
            {deviceTokens.length === 0 ? (
              <div className="text-center py-8 text-slate-500">
                暂无设备令牌，点击上方按钮添加
              </div>
            ) : (
              <div className="space-y-3">
                {deviceTokens.map((token) => (
                  <div key={token.id} className="bg-slate-900/50 rounded-lg p-4 border border-slate-700">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-2">
                          <h3 className="font-medium text-white">{token.name}</h3>
                          <span className={`inline-block px-2 py-0.5 text-xs rounded-full ${
                            token.platform === "android" 
                              ? "bg-blue-900/40 text-blue-300 border-blue-800" 
                              : "bg-purple-900/40 text-purple-300 border-purple-800"
                          }`}>
                            {token.platform}
                          </span>
                        </div>
                        <div className="space-y-1 text-sm">
                          <div className="text-slate-400">
                            <span className="text-slate-500">令牌：</span>
                            <span className="font-mono text-xs">{token.token.slice(0, 20)}...</span>
                          </div>
                          <div className="text-slate-400">
                            <span className="text-slate-500">用户 ID：</span>
                            {token.user_id.slice(0, 8)}...
                          </div>
                          <div className="text-slate-500 text-xs">
                            添加于 {new Date(token.created_at).toLocaleString()}
                          </div>
                        </div>
                      </div>
                      <div className="flex gap-2 ml-4">
                        <button
                          onClick={() => handleUseToken(token)}
                          className="bg-violet-600 hover:bg-violet-500 text-white px-3 py-1.5 rounded-md text-sm transition"
                        >
                          使用
                        </button>
                        <button
                          onClick={() => handleDeleteToken(token.id)}
                          className="bg-red-600 hover:bg-red-500 text-white px-3 py-1.5 rounded-md text-sm transition"
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 配置说明 */}
        <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
          <h2 className="text-lg font-semibold mb-4">配置说明</h2>
          <div className="space-y-3 text-sm text-slate-300">
            <div>
              <h3 className="font-medium text-white mb-1">FCM (Android) 配置</h3>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>在 .env 中设置 FCM_ENABLED=true</li>
                <li>提供 FCM_CREDENTIALS_PATH 指向 Firebase 服务账号密钥文件</li>
                <li>获取设备令牌并在此页面测试</li>
              </ul>
            </div>
            <div>
              <h3 className="font-medium text-white mb-1">APNs (iOS) 配置</h3>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>在 .env 中设置 APNS_ENABLED=true</li>
                <li>提供 APNS_TEAM_ID, APNS_KEY_ID, APNS_KEY_PATH</li>
                <li>设置正确的 APNS_BUNDLE_ID</li>
                <li>APNS_PRODUCTION: false (开发环境) / true (生产环境)</li>
              </ul>
            </div>
            <div>
              <h3 className="font-medium text-white mb-1">注意事项</h3>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>默认情况下推送服务是禁用的，需要配置相应环境变量</li>
                <li>测试前请确保已正确配置 FCM/APNs 凭证</li>
                <li>设备令牌需要从客户端应用获取</li>
                <li>生产环境请使用真实的设备令牌进行测试</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}