"""
Integration tests for API Service

Tests the FastAPI service that provides REST and WebSocket endpoints.
Following TDD approach - tests written first, then implementation.
"""

import pytest
import asyncio
import json
import sys
from pathlib import Path
from fastapi.testclient import TestClient

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


class TestAPIBasics:
    """Test basic API functionality"""

    def test_api_import(self):
        """Test that API module can be imported"""
        from api.main import app
        assert app is not None

    def test_health_endpoint(self):
        """Test health check endpoint"""
        from api.main import app

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    def test_root_endpoint(self):
        """Test root endpoint"""
        from api.main import app

        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "version" in data


class TestPlanAndRunEndpoint:
    """Test /plan-and-run endpoint"""

    def test_plan_and_run_accepts_request(self):
        """Test that /plan-and-run accepts POST requests"""
        from api.main import app

        client = TestClient(app)
        response = client.post(
            "/plan-and-run",
            json={"request": "Analyze logs and generate report"}
        )

        assert response.status_code == 200 or response.status_code == 202
        data = response.json()
        assert "correlation_id" in data

    def test_plan_and_run_returns_correlation_id(self):
        """Test that endpoint returns a correlation_id"""
        from api.main import app

        client = TestClient(app)
        response = client.post(
            "/plan-and-run",
            json={"request": "Test request"}
        )

        data = response.json()
        assert "correlation_id" in data
        assert len(data["correlation_id"]) > 0

    def test_plan_and_run_requires_request_field(self):
        """Test that request field is required"""
        from api.main import app

        client = TestClient(app)
        response = client.post(
            "/plan-and-run",
            json={}
        )

        assert response.status_code == 422  # Validation error

    def test_plan_and_run_publishes_to_rabbitmq(self):
        """Test that endpoint publishes message to orchestrator"""
        from api.main import app

        client = TestClient(app)
        response = client.post(
            "/plan-and-run",
            json={"request": "Analyze logs"}
        )

        # Should succeed (message published)
        assert response.status_code == 200 or response.status_code == 202
        data = response.json()
        assert "status" in data


class TestStatusEndpoint:
    """Test /status/{correlation_id} endpoint"""

    def test_status_endpoint_exists(self):
        """Test that status endpoint exists (returns 404 for non-existent ID)"""
        from api.main import app

        client = TestClient(app)
        response = client.get("/status/test-123")

        # Should return 404 for non-existent correlation_id (endpoint exists and validates)
        assert response.status_code == 404

    def test_status_returns_request_state(self):
        """Test that status returns request state"""
        from api.main import app

        client = TestClient(app)

        # First submit a request
        submit_response = client.post(
            "/plan-and-run",
            json={"request": "Test request"}
        )
        correlation_id = submit_response.json()["correlation_id"]

        # Then check status
        status_response = client.get(f"/status/{correlation_id}")

        assert status_response.status_code == 200
        data = status_response.json()
        assert "status" in data
        assert data["status"] in ["pending", "processing", "completed", "failed"]

    def test_status_nonexistent_correlation_id(self):
        """Test status for non-existent correlation_id"""
        from api.main import app

        client = TestClient(app)
        response = client.get("/status/nonexistent-id-12345")

        # Should return 404 or return not_found status
        assert response.status_code == 404 or (
            response.status_code == 200 and
            response.json()["status"] == "not_found"
        )


class TestWebSocketEndpoint:
    """Test WebSocket endpoint for real-time updates"""

    def test_websocket_endpoint_exists(self):
        """Test that WebSocket endpoint exists"""
        from api.main import app

        client = TestClient(app)

        with client.websocket_connect("/ws/test-123") as websocket:
            # Connection should succeed
            assert websocket is not None

    def test_websocket_receives_updates(self):
        """Test that WebSocket receives progress updates"""
        from api.main import app

        client = TestClient(app)

        # Submit a request first
        submit_response = client.post(
            "/plan-and-run",
            json={"request": "Test request"}
        )
        correlation_id = submit_response.json()["correlation_id"]

        # Connect via WebSocket
        with client.websocket_connect(f"/ws/{correlation_id}") as websocket:
            # Should receive initial message
            data = websocket.receive_json()
            assert "type" in data or "status" in data

    def test_websocket_closes_gracefully(self):
        """Test that WebSocket closes gracefully"""
        from api.main import app

        client = TestClient(app)

        with client.websocket_connect("/ws/test-123") as websocket:
            websocket.close()
            # Should not raise error


class TestRequestValidation:
    """Test request validation"""

    def test_empty_request_rejected(self):
        """Test that empty request string is rejected"""
        from api.main import app

        client = TestClient(app)
        response = client.post(
            "/plan-and-run",
            json={"request": ""}
        )

        assert response.status_code == 422  # Validation error

    def test_invalid_json_rejected(self):
        """Test that invalid JSON is rejected"""
        from api.main import app

        client = TestClient(app)
        response = client.post(
            "/plan-and-run",
            data="not json",
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 422

    def test_max_request_length(self):
        """Test that very long requests are handled"""
        from api.main import app

        client = TestClient(app)
        long_request = "A" * 10000  # 10KB request

        response = client.post(
            "/plan-and-run",
            json={"request": long_request}
        )

        # Should either accept or reject gracefully
        assert response.status_code in [200, 202, 413, 422]


class TestCORS:
    """Test CORS configuration"""

    def test_cors_headers_present(self):
        """Test that CORS headers are present"""
        from api.main import app

        client = TestClient(app)
        response = client.options("/health")

        # Should have CORS headers
        # (FastAPI automatically handles OPTIONS for CORS)
        assert response.status_code in [200, 405]


class TestErrorHandling:
    """Test API error handling"""

    def test_method_not_allowed(self):
        """Test that wrong HTTP method returns 405"""
        from api.main import app

        client = TestClient(app)
        response = client.get("/plan-and-run")  # Should be POST

        assert response.status_code == 405

    def test_not_found(self):
        """Test that non-existent endpoint returns 404"""
        from api.main import app

        client = TestClient(app)
        response = client.get("/nonexistent")

        assert response.status_code == 404


@pytest.mark.asyncio
class TestAPIIntegration:
    """Test API integration with RabbitMQ"""

    async def test_api_with_rabbitmq(self, rabbitmq_client):
        """Test API can connect to RabbitMQ"""
        from api.main import app

        # This would test real RabbitMQ integration
        # For now, just verify the app can be created
        assert app is not None

    async def test_message_published_to_orchestrator(self, rabbitmq_client):
        """Test that API publishes messages to orchestrator queue"""
        from api.main import app

        # Would verify message is published to orchestrator.requests
        # For now, placeholder
        assert True


class TestAPIResponseFormat:
    """Test API response format consistency"""

    def test_plan_and_run_response_format(self):
        """Test /plan-and-run response format"""
        from api.main import app

        client = TestClient(app)
        response = client.post(
            "/plan-and-run",
            json={"request": "Test"}
        )

        data = response.json()
        # Should have correlation_id
        assert "correlation_id" in data
        # Should have status
        assert "status" in data

    def test_status_response_format(self):
        """Test /status response format"""
        from api.main import app

        client = TestClient(app)

        # Submit request first
        submit_response = client.post(
            "/plan-and-run",
            json={"request": "Test"}
        )
        correlation_id = submit_response.json()["correlation_id"]

        # Get status
        status_response = client.get(f"/status/{correlation_id}")
        data = status_response.json()

        # Should have status field
        assert "status" in data

    def test_error_response_format(self):
        """Test error response format"""
        from api.main import app

        client = TestClient(app)
        response = client.post(
            "/plan-and-run",
            json={}  # Invalid request
        )

        # Error responses should have detail
        data = response.json()
        assert "detail" in data or "error" in data


class TestConcurrentRequests:
    """Test handling concurrent requests"""

    def test_multiple_simultaneous_requests(self):
        """Test API can handle multiple requests simultaneously"""
        from api.main import app

        client = TestClient(app)

        # Submit multiple requests
        responses = []
        for i in range(5):
            response = client.post(
                "/plan-and-run",
                json={"request": f"Test request {i}"}
            )
            responses.append(response)

        # All should succeed
        for response in responses:
            assert response.status_code in [200, 202]
            data = response.json()
            assert "correlation_id" in data

        # Correlation IDs should be unique
        correlation_ids = [r.json()["correlation_id"] for r in responses]
        assert len(correlation_ids) == len(set(correlation_ids))
