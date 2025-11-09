"""
CLI Client for Multi-Agent Orchestration System

A command-line interface for submitting requests to the orchestration API
and receiving results.
"""

import argparse
import sys
import time
import json
from pathlib import Path
import httpx
import asyncio
import websockets

# Default API URL
DEFAULT_API_URL = "http://localhost:8000"


def submit_request(request: str, api_url: str = DEFAULT_API_URL) -> dict:
    """
    Submit a request to the /plan-and-run endpoint.

    Args:
        request: User request text
        api_url: API base URL

    Returns:
        Response dict with correlation_id and status
    """
    url = f"{api_url}/plan-and-run"

    try:
        response = httpx.post(
            url,
            json={"request": request},
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()

    except httpx.HTTPError as e:
        print(f"Error submitting request: {e}")
        sys.exit(1)


def get_status(correlation_id: str, api_url: str = DEFAULT_API_URL) -> dict:
    """
    Get the status of a request.

    Args:
        correlation_id: Request correlation ID
        api_url: API base URL

    Returns:
        Status response dict
    """
    url = f"{api_url}/status/{correlation_id}"

    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        return response.json()

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            print(f"Request not found: {correlation_id}")
            sys.exit(1)
        else:
            print(f"Error getting status: {e}")
            sys.exit(1)

    except httpx.HTTPError as e:
        print(f"Error getting status: {e}")
        sys.exit(1)


def poll_status(
    correlation_id: str,
    api_url: str = DEFAULT_API_URL,
    interval: int = 2,
    timeout: int = 300
) -> dict:
    """
    Poll for request status until completion or timeout.

    Args:
        correlation_id: Request correlation ID
        api_url: API base URL
        interval: Polling interval in seconds
        timeout: Max time to wait in seconds

    Returns:
        Final status response dict
    """
    start_time = time.time()
    last_status = None

    print(f"\nPolling for results (timeout: {timeout}s)...")

    while True:
        # Check timeout
        elapsed = time.time() - start_time
        if elapsed > timeout:
            print(f"\nTimeout after {timeout}s")
            break

        # Get status
        status_response = get_status(correlation_id, api_url)
        current_status = status_response["status"]

        # Print status if changed
        if current_status != last_status:
            print(f"Status: {current_status}")
            last_status = current_status

        # Check if completed
        if current_status in ["completed", "failed"]:
            return status_response

        # Wait before next poll
        time.sleep(interval)

    # Return last status if timed out
    return get_status(correlation_id, api_url)


async def stream_websocket(
    correlation_id: str,
    api_url: str = DEFAULT_API_URL
):
    """
    Stream real-time updates via WebSocket.

    Args:
        correlation_id: Request correlation ID
        api_url: API base URL
    """
    # Convert http to ws
    ws_url = api_url.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/ws/{correlation_id}"

    print(f"\nConnecting to WebSocket...")

    try:
        async with websockets.connect(ws_url) as websocket:
            print("Connected! Streaming updates...\n")

            while True:
                try:
                    # Receive message
                    message = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=1.0
                    )

                    # Parse and display
                    data = json.loads(message)
                    print(f"Update: {json.dumps(data, indent=2)}")

                    # Check if completed
                    if data.get("status") in ["completed", "failed"]:
                        break

                except asyncio.TimeoutError:
                    # No message received, continue
                    continue

    except websockets.exceptions.WebSocketException as e:
        print(f"WebSocket error: {e}")


def format_output(status_response: dict):
    """
    Format and display the final output.

    Args:
        status_response: Status response dict
    """
    print("\n" + "=" * 60)
    print("ORCHESTRATION RESULT")
    print("=" * 60)

    print(f"\nCorrelation ID: {status_response['correlation_id']}")
    print(f"Status: {status_response['status']}")

    # Display progress
    if status_response.get("progress"):
        print(f"\nProgress Events: {len(status_response['progress'])}")

    # Display result
    if status_response.get("result"):
        print("\nResult:")
        print(json.dumps(status_response["result"], indent=2))

    # Display error
    if status_response.get("error"):
        print("\nError:")
        print(status_response["error"])

    print("\n" + "=" * 60)


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="CLI client for Multi-Agent Orchestration System"
    )

    parser.add_argument(
        "request",
        nargs="?",
        help="Request text to submit"
    )

    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"API base URL (default: {DEFAULT_API_URL})"
    )

    parser.add_argument(
        "--correlation-id",
        help="Check status of existing request"
    )

    parser.add_argument(
        "--poll",
        action="store_true",
        help="Poll for completion (when submitting request)"
    )

    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream updates via WebSocket (when submitting request)"
    )

    parser.add_argument(
        "--poll-interval",
        type=int,
        default=2,
        help="Polling interval in seconds (default: 2)"
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds (default: 300)"
    )

    args = parser.parse_args()

    # Check status mode
    if args.correlation_id:
        status_response = get_status(args.correlation_id, args.api_url)
        format_output(status_response)
        return

    # Submit request mode
    if not args.request:
        parser.print_help()
        sys.exit(1)

    print(f"Submitting request: {args.request}")

    # Submit request
    response = submit_request(args.request, args.api_url)

    correlation_id = response["correlation_id"]
    print(f"\nCorrelation ID: {correlation_id}")
    print(f"Status: {response['status']}")

    # Stream mode
    if args.stream:
        asyncio.run(stream_websocket(correlation_id, args.api_url))
        # Get final status
        status_response = get_status(correlation_id, args.api_url)
        format_output(status_response)
        return

    # Poll mode
    if args.poll:
        status_response = poll_status(
            correlation_id,
            args.api_url,
            args.poll_interval,
            args.timeout
        )
        format_output(status_response)
        return

    # Default: just submit and return
    print(f"\nUse --correlation-id {correlation_id} to check status later")


if __name__ == "__main__":
    main()
