import { useState, useEffect } from "react";

interface NetworkStatus {
  isOnline: boolean;
  effectiveType: string;
  downlink: number;
  rtt: number;
  saveData: boolean;
  isSlowConnection: boolean;
}

export function useNetworkStatus() {
  const [status, setStatus] = useState<NetworkStatus>({
    isOnline: navigator.onLine,
    effectiveType: "unknown",
    downlink: 0,
    rtt: 0,
    saveData: false,
    isSlowConnection: false,
  });

  useEffect(() => {
    const updateNetworkStatus = () => {
      const connection = (navigator as any).connection || (navigator as any).mozConnection || (navigator as any).webkitConnection;
      const isOnline = navigator.onLine;
      
      setStatus({
        isOnline,
        effectiveType: connection?.effectiveType || "unknown",
        downlink: connection?.downlink || 0,
        rtt: connection?.rtt || 0,
        saveData: connection?.saveData || false,
        isSlowConnection: isOnline && (
          (connection?.effectiveType === "slow-2g" || 
           connection?.effectiveType === "2g" ||
           connection?.downlink < 0.5 ||
           connection?.rtt > 300)
        ),
      });
    };

    const handleOnline = () => {
      console.log("Network back online");
      updateNetworkStatus();
    };

    const handleOffline = () => {
      console.log("Network offline");
      updateNetworkStatus();
    };

    const handleConnectionChange = () => {
      updateNetworkStatus();
    };

    // 初始状态
    updateNetworkStatus();

    // 监听网络状态变化
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    
    // 监听连接状态变化
    const connection = (navigator as any).connection || (navigator as any).mozConnection || (navigator as any).webkitConnection;
    if (connection) {
      connection.addEventListener("change", handleConnectionChange);
    }

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      if (connection) {
        connection.removeEventListener("change", handleConnectionChange);
      }
    };
  }, []);

  return status;
}