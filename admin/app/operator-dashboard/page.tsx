"use client";

import { useEffect, useState, useCallback } from "react";
import { apiFetch, Operator, LOGIN_PATH } from "@/lib/auth";
import AuthGate from "@/components/AuthGate";

// ── 类型定义 ─────────────────────────────────────────────────────

interface Task {
  task_id: string;
  user_id: string;
  conversation_id: string;
  priority: "P0" | "P1" | "P2" | "P3";
  trigger_reason: string;
  status: string;
  assigned_operator_id: string | null;
  locked_at: string | null;
  closed_at: string | null;
  created_at: string;
  last_message_at: string;
  channel: string;
  external_id: string;
  risk_level: string;
}

interface WebSocketMessage {
  type: string;
  trace_id?: string;
  message_id?: string;
  tasks?: Task[];
  task?: Task;
  task_id?: string;
}

// ── 优先级样式 ───────────────────────────────────────────────────

const priorityConfig = {
  P0: { label: "紧急", color: "bg-red-600", textColor: "text-red-400", border: "border-red-500" },
  P1: { label: "高", color: "bg-orange-600", textColor: "text-orange-400", border: "border-orange-500" },
  P2: { label: "中", color: "bg-yellow-600", textColor: "text-yellow-400", border: "border-yellow-500" },
  P3: { label: "低", color: "bg-slate-600", textColor: "text-slate-400", border: "border-slate-500" },
};

// ── 坐席看板组件 ────────────────────────────────────────────────

export default function OperatorDashboardPage() {
  return (
    <AuthGate>
      {(operator) => <OperatorDashboard operator={operator} />}
    </AuthGate>
  );
}

function OperatorDashboard({ operator }: { operator: Operator }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [wsStatus, setWsStatus] = useState<"connecting" | "connected" | "disconnected">("connecting");
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // WebSocket 连接
  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${proto}://${window.location.host}/ws/operators/tasks?operator_id=${encodeURIComponent(operator.operator_id)}`;
    
    const ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
      setWsStatus("connected");
      setError(null);
    };
    
    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as WebSocketMessage;
        
        switch (message.type) {
          case "connection.ready":
            console.log("WebSocket connection ready:", message);
            break;
            
          case "task.snapshot":
            // 初始任务快照
            if (message.tasks) {
              setTasks(message.tasks);
            }
            break;
            
          case "task.upsert":
            // 任务更新或新增
            if (message.task) {
              setTasks((prevTasks) => {
                const existingIndex = prevTasks.findIndex(t => t.task_id === message.task?.task_id);
                if (existingIndex >= 0) {
                  // 更新现有任务
                  const updatedTasks = [...prevTasks];
                  updatedTasks[existingIndex] = message.task!;
                  return updatedTasks;
                } else {
                  // 新增任务
                  return [...prevTasks, message.task!];
                }
              });
              
              // 发送 ACK 确认
              if (message.message_id) {
                ws.send(JSON.stringify({
                  type: "message.ack",
                  message_id: message.message_id,
                }));
              }
            }
            break;
            
          case "task.removed":
            // 任务移除
            if (message.task_id) {
              setTasks((prevTasks) => 
                prevTasks.filter(t => t.task_id !== message.task_id)
              );
              
              // 如果当前选中的任务被移除，清除选中状态
              setSelectedTask((prev) => 
                prev?.task_id === message.task_id ? null : prev
              );
              
              // 发送 ACK 确认
              if (message.message_id) {
                ws.send(JSON.stringify({
                  type: "message.ack",
                  message_id: message.message_id,
                }));
              }
            }
            break;
            
          case "user.upgraded":
            console.log("User upgraded:", message);
            // 可以在这里显示通知或更新 UI
            break;
            
          case "pong":
            // 心跳响应，无需处理
            break;
            
          default:
            console.log("Unknown message type:", message.type);
        }
      } catch (err) {
        console.error("Failed to parse WebSocket message:", err);
      }
    };
    
    ws.onclose = () => {
      setWsStatus("disconnected");
      setError("WebSocket 连接已断开，正在重新连接...");
      // 3秒后重新连接
      setTimeout(() => {
        setWsStatus("connecting");
      }, 3000);
    };
    
    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      setError("WebSocket 连接错误");
    };
    
    // 定期发送心跳
    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, 25000);
    
    return () => {
      clearInterval(pingInterval);
      ws.close();
    };
  }, [operator.operator_id]);
  
  // 当连接状态变化时，重新连接
  useEffect(() => {
    if (wsStatus === "connecting") {
      // 这会触发上面的 useEffect 重新建立连接
    }
  }, [wsStatus]);

  // 接受任务
  const handleAcceptTask = async (task: Task) => {
    setLoading(true);
    setError(null);
    try {
      await apiFetch(`/admin/handoff-tasks/${task.task_id}/accept`, {
        method: "POST",
      });
      // 任务接受后，WebSocket 会更新任务状态
      setSelectedTask(task);
    } catch (err) {
      setError(err instanceof Error ? err.message : "接受任务失败");
    } finally {
      setLoading(false);
    }
  };

  // 拒绝任务
  const handleRejectTask = async (task: Task) => {
    setLoading(true);
    setError(null);
    try {
      await apiFetch(`/admin/handoff-tasks/${task.task_id}/reject`, {
        method: "POST",
      });
      // 任务拒绝后，WebSocket 会更新任务状态
    } catch (err) {
      setError(err instanceof Error ? err.message : "拒绝任务失败");
    } finally {
      setLoading(false);
    }
  };

  // 格式化时间
  const formatTime = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 1) return "刚刚";
    if (diffMins < 60) return `${diffMins}分钟前`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}小时前`;
    return date.toLocaleDateString("zh-CN");
  };

  // 按优先级排序任务
  const sortedTasks = [...tasks].sort((a, b) => {
    const priorityOrder = { P0: 0, P1: 1, P2: 2, P3: 3 };
    return priorityOrder[a.priority] - priorityOrder[b.priority];
  });

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* 顶部导航栏 */}
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <a
              href="/admin"
              className="text-slate-400 hover:text-white transition"
            >
              ← 返回会话总览
            </a>
            <div>
              <h1 className="text-xl font-bold">坐席看板</h1>
              <p className="text-sm text-slate-400">
                欢迎回来，{operator.display_name || operator.username}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {/* WebSocket 状态指示器 */}
            <div className="flex items-center gap-2">
              <div
                className={`w-2 h-2 rounded-full ${
                  wsStatus === "connected" ? "bg-green-500" : 
                  wsStatus === "connecting" ? "bg-yellow-500 animate-pulse" : 
                  "bg-red-500"
                }`}
              />
              <span className="text-sm text-slate-400">
                {wsStatus === "connected" ? "已连接" : 
                 wsStatus === "connecting" ? "连接中..." : 
                 "已断开"}
              </span>
            </div>
            {/* 任务计数 */}
            <div className="text-sm text-slate-400">
              待处理任务: <span className="text-white font-semibold">{tasks.length}</span>
            </div>
            {/* 登出按钮 */}
            <button
              onClick={() => {
                if (typeof window !== "undefined") {
                  localStorage.removeItem("eris_admin_token");
                  localStorage.removeItem("eris_admin_operator");
                  window.location.href = LOGIN_PATH;
                }
              }}
              className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm transition"
            >
              登出
            </button>
          </div>
        </div>
      </header>

      {/* 错误提示 */}
      {error && (
        <div className="mx-6 mt-4 px-4 py-3 bg-red-900/40 border border-red-700 rounded-lg text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* 主内容区 */}
      <main className="p-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* 任务列表 */}
          <div className="lg:col-span-2">
            <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
              <div className="px-6 py-4 border-b border-slate-700">
                <h2 className="text-lg font-semibold">待处理任务</h2>
              </div>
              
              {sortedTasks.length === 0 ? (
                <div className="p-12 text-center text-slate-400">
                  <div className="text-4xl mb-4">📭</div>
                  <p>暂无待处理任务</p>
                </div>
              ) : (
                <div className="divide-y divide-slate-700">
                  {sortedTasks.map((task) => {
                    const config = priorityConfig[task.priority];
                    const isSelected = selectedTask?.task_id === task.task_id;
                    
                    return (
                      <div
                        key={task.task_id}
                        className={`p-4 hover:bg-slate-700/50 transition cursor-pointer ${
                          isSelected ? "bg-slate-700/50" : ""
                        }`}
                        onClick={() => setSelectedTask(task)}
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            {/* 优先级标签 */}
                            <div className="flex items-center gap-2 mb-2">
                              <span
                                className={`px-2 py-1 rounded text-xs font-semibold ${config.color} ${config.textColor}`}
                              >
                                {config.label}
                              </span>
                              <span className="text-xs text-slate-400">
                                {formatTime(task.created_at)}
                              </span>
                            </div>
                            
                            {/* 任务信息 */}
                            <div className="space-y-1">
                              <div className="text-sm">
                                <span className="text-slate-400">用户:</span>{" "}
                                <span className="text-slate-200">{task.external_id}</span>
                              </div>
                              <div className="text-sm">
                                <span className="text-slate-400">渠道:</span>{" "}
                                <span className="text-slate-200">{task.channel}</span>
                              </div>
                              <div className="text-sm">
                                <span className="text-slate-400">原因:</span>{" "}
                                <span className="text-slate-200">{task.trigger_reason}</span>
                              </div>
                              <div className="text-sm">
                                <span className="text-slate-400">风险等级:</span>{" "}
                                <span className="text-slate-200">{task.risk_level}</span>
                              </div>
                            </div>
                          </div>
                          
                          {/* 操作按钮 */}
                          <div className="flex flex-col gap-2">
                            {!task.assigned_operator_id ? (
                              <>
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleAcceptTask(task);
                                  }}
                                  disabled={loading}
                                  className="px-3 py-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded text-sm transition"
                                >
                                  接受
                                </button>
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleRejectTask(task);
                                  }}
                                  disabled={loading}
                                  className="px-3 py-1.5 bg-red-600 hover:bg-red-500 disabled:opacity-50 rounded text-sm transition"
                                >
                                  拒绝
                                </button>
                              </>
                            ) : task.assigned_operator_id === operator.operator_id ? (
                              <span className="px-3 py-1.5 bg-blue-600 rounded text-sm">
                                处理中
                              </span>
                            ) : (
                              <span className="px-3 py-1.5 bg-slate-600 rounded text-sm">
                                已分配
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {/* 任务详情 */}
          <div className="lg:col-span-1">
            <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden sticky top-6">
              <div className="px-6 py-4 border-b border-slate-700">
                <h2 className="text-lg font-semibold">任务详情</h2>
              </div>
              
              {selectedTask ? (
                <div className="p-6 space-y-4">
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">任务 ID</label>
                    <div className="text-sm font-mono text-slate-200">{selectedTask.task_id}</div>
                  </div>
                  
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">优先级</label>
                    <span
                      className={`px-2 py-1 rounded text-xs font-semibold ${priorityConfig[selectedTask.priority].color} ${priorityConfig[selectedTask.priority].textColor}`}
                    >
                      {priorityConfig[selectedTask.priority].label}
                    </span>
                  </div>
                  
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">状态</label>
                    <div className="text-sm text-slate-200">{selectedTask.status}</div>
                  </div>
                  
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">用户 ID</label>
                    <div className="text-sm font-mono text-slate-200">{selectedTask.user_id}</div>
                  </div>
                  
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">对话 ID</label>
                    <div className="text-sm font-mono text-slate-200">{selectedTask.conversation_id}</div>
                  </div>
                  
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">外部 ID</label>
                    <div className="text-sm text-slate-200">{selectedTask.external_id}</div>
                  </div>
                  
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">渠道</label>
                    <div className="text-sm text-slate-200">{selectedTask.channel}</div>
                  </div>
                  
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">触发原因</label>
                    <div className="text-sm text-slate-200">{selectedTask.trigger_reason}</div>
                  </div>
                  
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">风险等级</label>
                    <div className="text-sm text-slate-200">{selectedTask.risk_level}</div>
                  </div>
                  
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">分配坐席</label>
                    <div className="text-sm text-slate-200">
                      {selectedTask.assigned_operator_id || "未分配"}
                    </div>
                  </div>
                  
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">创建时间</label>
                    <div className="text-sm text-slate-200">
                      {new Date(selectedTask.created_at).toLocaleString("zh-CN")}
                    </div>
                  </div>
                  
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">最后消息时间</label>
                    <div className="text-sm text-slate-200">
                      {selectedTask.last_message_at 
                        ? new Date(selectedTask.last_message_at).toLocaleString("zh-CN")
                        : "无"}
                    </div>
                  </div>
                  
                  {/* 操作按钮 */}
                  <div className="pt-4 border-t border-slate-700">
                    {!selectedTask.assigned_operator_id ? (
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleAcceptTask(selectedTask)}
                          disabled={loading}
                          className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded text-sm font-medium transition"
                        >
                          接受任务
                        </button>
                        <button
                          onClick={() => handleRejectTask(selectedTask)}
                          disabled={loading}
                          className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-500 disabled:opacity-50 rounded text-sm font-medium transition"
                        >
                          拒绝任务
                        </button>
                      </div>
                    ) : selectedTask.assigned_operator_id === operator.operator_id ? (
                      <button
                        onClick={() => {
                          // 跳转到对话详情页面
                          window.location.href = `/admin/?conversation_id=${selectedTask.conversation_id}`;
                        }}
                        className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium transition"
                      >
                        开始处理
                      </button>
                    ) : (
                      <div className="text-sm text-slate-400 text-center">
                        该任务已分配给其他坐席
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="p-12 text-center text-slate-400">
                  <div className="text-4xl mb-4">📋</div>
                  <p>选择一个任务查看详情</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}