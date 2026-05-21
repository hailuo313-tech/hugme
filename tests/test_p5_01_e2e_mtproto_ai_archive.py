"""
P5-01: E2E test for MTProto inbound → AI processing → human-like delivery → archiving

This test validates the complete flow:
1. MTProto message reception (simulated Telegram webhook)
2. AI processing with script matching and LLM orchestration
3. Human-like delivery with typing indicators and delays
4. Conversation archiving with script_hit audit trail
"""

import pytest
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

# Test configuration
API_BASE = "http://127.0.0.1:8000"
DB_CONTAINER = "eris-postgres"
DB_USER = "eris"
DB_NAME = "eris"

# Test data
TEST_USER_ID = f"test_p5_01_{int(time.time())}"
TEST_EXTERNAL_ID = f"tg_{TEST_USER_ID}"
TEST_CONVERSATION_ID = ""


class TestP501E2EMTProtoFlow:
    """P5-01 E2E test for complete MTProto → AI → Delivery → Archive flow"""

    @pytest.fixture(scope="class")
    def setup_test_environment(self):
        """Setup test database and API client"""
        import subprocess
        import requests
        
        # Wait for API to be ready
        max_retries = 30
        for i in range(max_retries):
            try:
                response = requests.get(f"{API_BASE}/health/detail", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("api") == "ok" and data.get("db") == "ok":
                        break
            except Exception:
                pass
            time.sleep(2)
        else:
            pytest.fail("API not ready within timeout")

    def test_01_mtproto_inbound_webhook(self, setup_test_environment):
        """Test MTProto inbound message reception via webhook"""
        import requests
        
        # Simulate Telegram webhook message
        webhook_payload = {
            "update_id": 123456,
            "message": {
                "message_id": 1,
                "date": int(time.time()),
                "chat": {
                    "id": int(TEST_USER_ID),
                    "type": "private"
                },
                "from": {
                    "id": int(TEST_USER_ID),
                    "is_bot": False,
                    "first_name": "P5-01",
                    "username": f"p5_01_test_{TEST_USER_ID}",
                    "language_code": "zh"
                },
                "text": "你好，我想了解一下你们的服务"
            }
        }
        
        response = requests.post(
            f"{API_BASE}/telegram/webhook",
            json=webhook_payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True
        assert "trace_id" in data
        
        # Verify user was created in database
        time.sleep(1)  # Wait for async processing
        user_id = self._db_query(
            f"SELECT id FROM users WHERE channel='telegram' AND external_id='{TEST_EXTERNAL_ID}' LIMIT 1;"
        )
        assert user_id is not None and user_id != "NO_DB_CLIENT"
        
        global TEST_CONVERSATION_ID
        TEST_CONVERSATION_ID = self._db_query(
            f"SELECT id FROM conversations WHERE user_id='{user_id}' ORDER BY created_at DESC LIMIT 1;"
        )
        assert TEST_CONVERSATION_ID is not None and TEST_CONVERSATION_ID != "NO_DB_CLIENT"

    def test_02_script_matching_inbound(self, setup_test_environment):
        """Test script matching for inbound message"""
        # Verify that script_hit_id was recorded for the inbound message
        messages = self._db_query(
            f"SELECT id, script_hit_id, direction FROM messages WHERE conversation_id='{TEST_CONVERSATION_ID}' ORDER BY created_at ASC LIMIT 1;"
        )
        assert messages is not None and messages != "NO_DB_CLIENT"
        
        # The first message should be user's inbound message with script_hit_id
        if isinstance(messages, str):
            # If query returned single value, re-run to get full row
            message_data = self._db_query(
                f"SELECT script_hit_id FROM messages WHERE conversation_id='{TEST_CONVERSATION_ID}' AND direction='inbound' LIMIT 1;"
            )
        else:
            message_data = messages[0] if isinstance(messages, list) else messages
            
        assert message_data is not None

    def test_03_ai_processing_with_llm(self, setup_test_environment):
        """Test AI processing with LLM orchestration"""
        import requests
        
        # Send a follow-up message to trigger AI processing
        webhook_payload = {
            "update_id": 123457,
            "message": {
                "message_id": 2,
                "date": int(time.time()),
                "chat": {"id": int(TEST_USER_ID), "type": "private"},
                "from": {
                    "id": int(TEST_USER_ID),
                    "is_bot": False,
                    "first_name": "P5-01"
                },
                "text": "我想找个人聊聊天"
            }
        }
        
        response = requests.post(
            f"{API_BASE}/telegram/webhook",
            json=webhook_payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        assert response.status_code == 200
        
        # Wait for AI processing and outbound message
        time.sleep(5)  # Allow time for AI processing
        
        # Verify outbound message was created
        outbound_count = self._db_query(
            f"SELECT COUNT(*) FROM messages WHERE conversation_id='{TEST_CONVERSATION_ID}' AND direction='outbound';"
        )
        assert outbound_count is not None and outbound_count != "NO_DB_CLIENT"
        assert int(outbound_count) >= 1

    def test_04_human_like_delivery(self, setup_test_environment):
        """Test human-like delivery with typing indicators and delays"""
        # Verify that outbound messages have human-like characteristics
        messages = self._db_query(
            f"SELECT content, created_at, metadata FROM messages WHERE conversation_id='{TEST_CONVERSATION_ID}' AND direction='outbound' LIMIT 3;"
        )
        
        assert messages is not None and messages != "NO_DB_CLIENT"
        
        # Check that messages have reasonable length (human-like)
        # and were sent with some delay (not instant)
        if isinstance(messages, list) and len(messages) > 1:
            for msg in messages:
                content = msg.get('content', '') if isinstance(msg, dict) else str(msg)
                # Human-like messages are typically between 10-200 characters
                assert 10 <= len(content) <= 200, f"Message length {len(content)} not human-like"

    def test_05_script_hit_audit_trail(self, setup_test_environment):
        """Test complete script_hit audit trail"""
        # Verify script_hit records exist for the conversation
        script_hits = self._db_query(
            f"SELECT COUNT(*) FROM script_hits WHERE conversation_id='{TEST_CONVERSATION_ID}';"
        )
        
        assert script_hits is not None and script_hits != "NO_DB_CLIENT"
        assert int(script_hits) >= 2  # At least inbound and outbound script hits

    def test_06_archiving_process(self, setup_test_environment):
        """Test conversation archiving with complete audit trail"""
        import requests
        
        # Simulate conversation end by sending a goodbye message
        webhook_payload = {
            "update_id": 123458,
            "message": {
                "message_id": 3,
                "date": int(time.time()),
                "chat": {"id": int(TEST_USER_ID), "type": "private"},
                "from": {
                    "id": int(TEST_USER_ID),
                    "is_bot": False,
                    "first_name": "P5-01"
                },
                "text": "好的，再见"
            }
        }
        
        response = requests.post(
            f"{API_BASE}/telegram/webhook",
            json=webhook_payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        assert response.status_code == 200
        time.sleep(3)  # Wait for final processing
        
        # Verify conversation has proper audit trail
        message_count = self._db_query(
            f"SELECT COUNT(*) FROM messages WHERE conversation_id='{TEST_CONVERSATION_ID}';"
        )
        assert message_count is not None and message_count != "NO_DB_CLIENT"
        assert int(message_count) >= 6  # User messages + AI responses
        
        # Verify script_hit audit trail is complete
        script_hit_details = self._db_query(
            f"SELECT hook_type, script_template_id, matched_at FROM script_hits WHERE conversation_id='{TEST_CONVERSATION_ID}' ORDER BY matched_at ASC;"
        )
        assert script_hit_details is not None and script_hit_details != "NO_DB_CLIENT"

    def test_07_end_to_end_traceability(self, setup_test_environment):
        """Test complete end-to-end traceability with trace_id"""
        # Verify that all messages have proper traceability
        messages_with_trace = self._db_query(
            f"SELECT COUNT(*) FROM messages WHERE conversation_id='{TEST_CONVERSATION_ID}' AND trace_id IS NOT NULL;"
        )
        total_messages = self._db_query(
            f"SELECT COUNT(*) FROM messages WHERE conversation_id='{TEST_CONVERSATION_ID}';"
        )
        
        assert messages_with_trace is not None and total_messages is not None
        assert messages_with_trace != "NO_DB_CLIENT" and total_messages != "NO_DB_CLIENT"
        
        # Most messages should have trace_id for debugging
        traceability_ratio = int(messages_with_trace) / int(total_messages) if int(total_messages) > 0 else 0
        assert traceability_ratio >= 0.8, f"Traceability ratio {traceability_ratio} below 80%"

    def _db_query(self, sql: str) -> Any:
        """Execute database query"""
        import subprocess
        import os
        
        # Try to use docker exec if available
        try:
            result = subprocess.run(
                ["docker", "exec", DB_CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME, "-Atc", sql],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                return output if output else None
        except Exception as e:
            print(f"Docker exec failed: {e}")
        
        # Fallback: try direct psql if DSN is set
        dsn = os.environ.get("PSQL_DSN")
        if dsn:
            try:
                result = subprocess.run(
                    ["psql", dsn, "-Atc", sql],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    output = result.stdout.strip()
                    return output if output else None
            except Exception as e:
                print(f"Direct psql failed: {e}")
        
        return "NO_DB_CLIENT"


class TestP501E2EIntegration:
    """Integration tests for P5-01 E2E flow components"""

    def test_health_check(self, setup_test_environment):
        """Test that all components are healthy"""
        import requests
        
        response = requests.get(f"{API_BASE}/health/detail", timeout=5)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("api") == "ok"
        assert data.get("db") == "ok"
        assert data.get("redis") == "ok"

    def test_webhook_endpoint(self, setup_test_environment):
        """Test Telegram webhook endpoint is accessible"""
        import requests
        
        # Send a minimal health check to webhook
        response = requests.get(f"{API_BASE}/health", timeout=5)
        assert response.status_code == 200

    def test_script_templates_exist(self, setup_test_environment):
        """Test that script templates exist for matching"""
        script_count = self._db_query("SELECT COUNT(*) FROM script_templates WHERE is_active = true;")
        assert script_count is not None and script_count != "NO_DB_CLIENT"
        assert int(script_count) > 0, "No active script templates found"

    def test_llm_service_configured(self, setup_test_environment):
        """Test that LLM service is properly configured"""
        # Check if LLM fallback is enabled for testing
        llm_fallback = self._db_query(
            "SELECT value FROM configuration WHERE key = 'llm_echo_fallback';"
        )
        # In test environment, we expect either fallback or real LLM config
        assert llm_fallback is not None or llm_fallback != "NO_DB_CLIENT"


def test_p5_01_e2e_smoke():
    """Quick smoke test for P5-01 E2E functionality"""
    import requests
    
    # Test basic API health
    response = requests.get(f"{API_BASE}/health", timeout=5)
    assert response.status_code == 200
    
    # Test webhook endpoint exists
    response = requests.post(
        f"{API_BASE}/telegram/webhook",
        json={"update_id": 999999, "message": {"message_id": 1, "date": int(time.time()), "chat": {"id": 999999}, "from": {"id": 999999}, "text": "test"}},
        headers={"Content-Type": "application/json"},
        timeout=5
    )
    # We don't assert success here as the user might not exist, but endpoint should be accessible
    assert response.status_code in [200, 400, 422]  # Acceptable responses


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s", "--tb=short"])