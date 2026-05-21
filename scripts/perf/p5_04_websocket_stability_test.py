#!/usr/bin/env python3
"""
P5-04: 72-hour WebSocket long-term stability test

This script performs long-term WebSocket stability testing with zero message loss verification.
It monitors connection stability, message delivery, and generates comprehensive reports.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
import websockets
import websockets.exceptions
import statistics


# Configuration
WS_URL = os.environ.get("WS_URL", "ws://127.0.0.1:8000/ws/operators/tasks")
OPERATOR_ID = os.environ.get("OPERATOR_ID", "test_p5_04_operator")
TEST_DURATION_HOURS = int(os.environ.get("P5_04_TEST_DURATION_HOURS", "72"))
PING_INTERVAL_SECONDS = int(os.environ.get("P5_04_PING_INTERVAL", "30"))
REPORT_INTERVAL_SECONDS = int(os.environ.get("P5_04_REPORT_INTERVAL", "3600"))  # 1 hour
OUTPUT_DIR = os.environ.get("P5_04_OUTPUT_DIR", "scripts/perf/reports")


@dataclass
class MessageStats:
    """Message statistics"""
    sent_count: int = 0
    received_count: int = 0
    lost_count: int = 0
    expected_sequence: int = 0
    last_sequence: int = -1
    sequence_gaps: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class ConnectionStats:
    """Connection statistics"""
    connect_attempts: int = 0
    successful_connects: int = 0
    failed_connects: int = 0
    disconnect_count: int = 0
    reconnect_count: int = 0
    total_uptime_seconds: float = 0
    total_downtime_seconds: float = 0
    current_session_start: Optional[float] = None
    last_disconnect_time: Optional[float] = None


@dataclass
class TestReport:
    """Comprehensive test report"""
    test_start_time: str
    test_end_time: str
    duration_hours: float
    operator_id: str
    ws_url: str
    
    # Connection metrics
    connection_stats: dict[str, Any]
    
    # Message metrics
    message_stats: dict[str, Any]
    
    # Stability metrics
    uptime_percentage: float
    reconnect_count: int
    ping_success_rate: float
    
    # Acceptance criteria
    zero_message_loss: bool
    message_loss_details: str
    
    # Recommendations
    recommendations: list[str]


class WebSocketStabilityTester:
    """WebSocket long-term stability tester"""
    
    def __init__(self, ws_url: str, operator_id: str, duration_hours: int):
        self.ws_url = ws_url
        self.operator_id = operator_id
        self.duration_hours = duration_hours
        self.test_start_time = datetime.now()
        self.test_end_time = self.test_start_time + timedelta(hours=duration_hours)
        
        self.message_stats = MessageStats()
        self.connection_stats = ConnectionStats()
        self.ping_stats = {"sent": 0, "received": 0, "failed": 0}
        
        self.running = False
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.report_count = 0
        
    async def connect(self) -> bool:
        """Establish WebSocket connection"""
        self.connection_stats.connect_attempts += 1
        try:
            self.websocket = await websockets.connect(
                self.ws_url,
                ping_interval=None,  # We handle ping ourselves
                ping_timeout=None,
                close_timeout=10
            )
            
            self.connection_stats.successful_connects += 1
            self.connection_stats.current_session_start = time.time()
            
            # Wait for connection.ready
            await self.wait_for_connection_ready()
            
            return True
            
        except Exception as e:
            self.connection_stats.failed_connects += 1
            print(f"Connection failed: {e}")
            return False
    
    async def wait_for_connection_ready(self, timeout: float = 10.0) -> bool:
        """Wait for connection.ready message"""
        try:
            async with asyncio.timeout(timeout):
                while True:
                    message = await self.websocket.recv()
                    data = json.loads(message)
                    if data.get("type") == "connection.ready":
                        print(f"✅ Connection ready: {data}")
                        return True
        except asyncio.TimeoutError:
            print("❌ Timeout waiting for connection.ready")
            return False
        except Exception as e:
            print(f"❌ Error waiting for connection.ready: {e}")
            return False
    
    async def send_ping(self) -> bool:
        """Send ping message"""
        if not self.websocket or self.websocket.closed:
            return False
            
        try:
            ping_message = {"type": "ping", "sequence": self.message_stats.sent_count}
            await self.websocket.send(json.dumps(ping_message))
            self.ping_stats["sent"] += 1
            self.message_stats.sent_count += 1
            return True
        except Exception as e:
            self.ping_stats["failed"] += 1
            print(f"Ping failed: {e}")
            return False
    
    async def send_task_ack(self, task_id: str) -> bool:
        """Send task acknowledgment"""
        if not self.websocket or self.websocket.closed:
            return False
            
        try:
            ack_message = {"type": "task.ack", "task_id": task_id}
            await self.websocket.send(json.dumps(ack_message))
            self.message_stats.sent_count += 1
            return True
        except Exception as e:
            print(f"Task ACK failed: {e}")
            return False
    
    async def receive_message(self) -> Optional[dict[str, Any]]:
        """Receive and process message"""
        if not self.websocket or self.websocket.closed:
            return None
            
        try:
            message = await self.websocket.recv()
            data = json.loads(message)
            self.message_stats.received_count += 1
            
            # Handle pong responses
            if data.get("type") == "pong":
                self.ping_stats["received"] += 1
                
            # Handle task messages
            elif data.get("type") in ["task.snapshot", "task.upsert", "task.removed"]:
                # Could send ACK for task messages
                if data.get("type") == "task.upsert":
                    task_id = data.get("task", {}).get("task_id")
                    if task_id:
                        await self.send_task_ack(task_id)
            
            return data
            
        except Exception as e:
            print(f"Receive error: {e}")
            return None
    
    def check_message_loss(self) -> bool:
        """Check for message loss"""
        # For ping/pong, we track if pings were responded to
        if self.ping_stats["sent"] > 0:
            loss_rate = (self.ping_stats["sent"] - self.ping_stats["received"]) / self.ping_stats["sent"]
            return loss_rate == 0.0
        return True
    
    def calculate_uptime(self) -> float:
        """Calculate uptime percentage"""
        if self.connection_stats.current_session_start:
            self.connection_stats.total_uptime_seconds += (
                time.time() - self.connection_stats.current_session_start
            )
            self.connection_stats.current_session_start = time.time()
        
        total_time = self.connection_stats.total_uptime_seconds + self.connection_stats.total_downtime_seconds
        if total_time > 0:
            return (self.connection_stats.total_uptime_seconds / total_time) * 100
        return 0.0
    
    async def handle_disconnect(self):
        """Handle disconnect event"""
        if self.connection_stats.current_session_start:
            session_duration = time.time() - self.connection_stats.current_session_start
            self.connection_stats.total_uptime_seconds += session_duration
            self.connection_stats.current_session_start = None
        
        self.connection_stats.disconnect_count += 1
        self.connection_stats.last_disconnect_time = time.time()
        self.connection_stats.reconnect_count += 1
        
        print(f"❌ Disconnected at {datetime.now().isoformat()}")
    
    async def generate_report(self) -> TestReport:
        """Generate comprehensive test report"""
        self.calculate_uptime()
        
        elapsed = (datetime.now() - self.test_start_time).total_seconds() / 3600
        zero_loss = self.check_message_loss()
        
        ping_success_rate = 0.0
        if self.ping_stats["sent"] > 0:
            ping_success_rate = (self.ping_stats["received"] / self.ping_stats["sent"]) * 100
        
        loss_details = f"Sent: {self.ping_stats['sent']}, Received: {self.ping_stats['received']}, Lost: {self.ping_stats['sent'] - self.ping_stats['received']}"
        
        recommendations = []
        if not zero_loss:
            recommendations.append(f"❌ Message loss detected: {loss_details}")
        else:
            recommendations.append("✅ Zero message loss achieved")
        
        if self.connection_stats.reconnect_count > 5:
            recommendations.append(f"⚠️ High reconnect count: {self.connection_stats.reconnect_count}")
        
        if self.connection_stats.total_downtime_seconds > 300:  # 5 minutes
            recommendations.append(f"⚠️ Significant downtime: {self.connection_stats.total_downtime_seconds}s")
        
        report = TestReport(
            test_start_time=self.test_start_time.isoformat(),
            test_end_time=datetime.now().isoformat(),
            duration_hours=elapsed,
            operator_id=self.operator_id,
            ws_url=self.ws_url,
            
            connection_stats={
                "connect_attempts": self.connection_stats.connect_attempts,
                "successful_connects": self.connection_stats.successful_connects,
                "failed_connects": self.connection_stats.failed_connects,
                "disconnect_count": self.connection_stats.disconnect_count,
                "reconnect_count": self.connection_stats.reconnect_count,
                "uptime_percentage": round(self.calculate_uptime(), 2),
                "total_uptime_seconds": round(self.connection_stats.total_uptime_seconds, 2),
                "total_downtime_seconds": round(self.connection_stats.total_downtime_seconds, 2),
            },
            
            message_stats={
                "sent_count": self.message_stats.sent_count,
                "received_count": self.message_stats.received_count,
                "lost_count": self.message_stats.lost_count,
                "ping_sent": self.ping_stats["sent"],
                "ping_received": self.ping_stats["received"],
                "ping_failed": self.ping_stats["failed"],
                "ping_success_rate": round(ping_success_rate, 2),
            },
            
            uptime_percentage=round(self.calculate_uptime(), 2),
            reconnect_count=self.connection_stats.reconnect_count,
            ping_success_rate=round(ping_success_rate, 2),
            
            zero_message_loss=zero_loss,
            message_loss_details=loss_details,
            
            recommendations=recommendations
        )
        
        return report
    
    def save_report(self, report: TestReport) -> str:
        """Save report to file"""
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"p5_04_websocket_stability_report_{timestamp}.json"
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({
                "report": report.__dict__,
                "raw_stats": {
                    "message_stats": self.message_stats.__dict__,
                    "connection_stats": self.connection_stats.__dict__,
                    "ping_stats": self.ping_stats
                }
            }, f, indent=2, ensure_ascii=False, default=str)
        
        return filepath
    
    async def run_test(self):
        """Run the stability test"""
        self.running = True
        print(f"🚀 Starting P5-04 WebSocket Stability Test")
        print(f"📊 Duration: {self.duration_hours} hours")
        print(f"🌐 WebSocket URL: {self.ws_url}")
        print(f"👤 Operator ID: {self.operator_id}")
        print(f"⏰ Start Time: {self.test_start_time.isoformat()}")
        print(f"📁 Output Directory: {OUTPUT_DIR}")
        print()
        
        last_ping_time = time.time()
        last_report_time = time.time()
        
        while self.running and datetime.now() < self.test_end_time:
            # Try to connect if not connected
            if not self.websocket or self.websocket.closed:
                print("🔄 Connecting to WebSocket...")
                if await self.connect():
                    print("✅ Connected successfully")
                else:
                    print("❌ Connection failed, retrying in 10 seconds...")
                    await asyncio.sleep(10)
                    continue
            
            # Send periodic pings
            current_time = time.time()
            if current_time - last_ping_time >= PING_INTERVAL_SECONDS:
                await self.send_ping()
                last_ping_time = current_time
            
            # Generate periodic reports
            if current_time - last_report_time >= REPORT_INTERVAL_SECONDS:
                print(f"📈 Generating periodic report (Report #{self.report_count + 1})...")
                report = await self.generate_report()
                report_path = self.save_report(report)
                print(f"💾 Report saved to: {report_path}")
                print(f"📊 Uptime: {report.uptime_percentage}%, Reconnects: {report.reconnect_count}")
                print(f"📨 Messages: Sent={report.message_stats['sent_count']}, Received={report.message_stats['received_count']}")
                self.report_count += 1
                last_report_time = current_time
            
            # Receive messages
            try:
                await self.receive_message()
            except Exception as e:
                print(f"Receive error: {e}")
                await self.handle_disconnect()
            
            # Small delay to prevent tight loop
            await asyncio.sleep(0.1)
        
        # Final report
        print(f"\n🏁 Test completed at {datetime.now().isoformat()}")
        print(f"📈 Generating final report...")
        final_report = await self.generate_report()
        final_report_path = self.save_report(final_report)
        print(f"💾 Final report saved to: {final_report_path}")
        
        # Print summary
        print(f"\n📋 Final Summary:")
        print(f"   Duration: {final_report.duration_hours:.2f} hours")
        print(f"   Uptime: {final_report.uptime_percentage}%")
        print(f"   Reconnects: {final_report.reconnect_count}")
        print(f"   Messages Sent: {final_report.message_stats['sent_count']}")
        print(f"   Messages Received: {final_report.message_stats['received_count']}")
        print(f"   Ping Success Rate: {final_report.ping_success_rate}%")
        print(f"   Zero Message Loss: {'✅ YES' if final_report.zero_message_loss else '❌ NO'}")
        
        print(f"\n💡 Recommendations:")
        for rec in final_report.recommendations:
            print(f"   {rec}")
        
        # Close connection
        if self.websocket and not self.websocket.closed:
            await self.websocket.close()
        
        return final_report.zero_message_loss


async def main():
    """Main entry point"""
    tester = WebSocketStabilityTester(
        ws_url=WS_URL,
        operator_id=OPERATOR_ID,
        duration_hours=TEST_DURATION_HOURS
    )
    
    try:
        zero_loss = await tester.run_test()
        return 0 if zero_loss else 1
    except KeyboardInterrupt:
        print("\n⚠️ Test interrupted by user")
        return 2
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        return 3


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    raise SystemExit(exit_code)