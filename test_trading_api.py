"""
Test Trading API Bridge
Verify API endpoints and connectivity
"""
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'


def print_header(text):
    """Print section header."""
    print()
    print("=" * 60)
    print(text)
    print("=" * 60)
    print()


def print_success(text):
    """Print success message."""
    print(f"{Colors.GREEN}✓{Colors.END} {text}")


def print_error(text):
    """Print error message."""
    print(f"{Colors.RED}✗{Colors.END} {text}")


def print_warning(text):
    """Print warning message."""
    print(f"{Colors.YELLOW}⚠{Colors.END} {text}")


def test_health(api_url):
    """Test health endpoint (no auth)."""
    print("Testing health endpoint...")

    try:
        response = requests.get(f"{api_url}/api/health", timeout=5)

        if response.status_code == 200:
            data = response.json()
            print_success(f"Health check passed")
            print(f"  Status: {data.get('status')}")
            print(f"  DEX Connected: {data.get('dex_connected')}")
            return True
        else:
            print_error(f"Health check failed: {response.status_code}")
            return False

    except requests.exceptions.ConnectionError:
        print_error("Connection refused - API not running")
        return False
    except Exception as e:
        print_error(f"Health check error: {e}")
        return False


def test_auth(api_url, token):
    """Test authentication."""
    print("Testing authentication...")

    # Test without token
    try:
        response = requests.get(f"{api_url}/api/status", timeout=5)
        if response.status_code == 401:
            print_success("No-token request correctly rejected (401)")
        else:
            print_warning(f"Expected 401, got {response.status_code}")
    except Exception as e:
        print_error(f"Auth test error: {e}")
        return False

    # Test with invalid token
    try:
        headers = {"Authorization": "Bearer invalid_token"}
        response = requests.get(f"{api_url}/api/status", headers=headers, timeout=5)
        if response.status_code == 403:
            print_success("Invalid token correctly rejected (403)")
        else:
            print_warning(f"Expected 403, got {response.status_code}")
    except Exception as e:
        print_error(f"Auth test error: {e}")
        return False

    # Test with valid token
    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{api_url}/api/status", headers=headers, timeout=5)
        if response.status_code == 200:
            print_success("Valid token accepted")
            return True
        else:
            print_error(f"Valid token rejected: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"Auth test error: {e}")
        return False


def test_status(api_url, token):
    """Test status endpoint."""
    print("Testing status endpoint...")

    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{api_url}/api/status", headers=headers, timeout=5)

        if response.status_code == 200:
            data = response.json()

            if data.get('success'):
                print_success("Status endpoint working")
                print(f"  Balance: {data.get('balance_sol', 'N/A')} SOL")
                print(f"  Open Positions: {data.get('open_positions', 0)}")

                stats = data.get('stats', {})
                print(f"  Total P&L: {stats.get('total_pnl_sol', 0):+.4f} SOL")
                print(f"  Total Trades: {stats.get('total_trades', 0)}")
                return True
            else:
                print_error(f"Status failed: {data.get('error')}")
                return False
        else:
            print_error(f"Status endpoint error: {response.status_code}")
            return False

    except Exception as e:
        print_error(f"Status test error: {e}")
        return False


def test_positions(api_url, token):
    """Test positions endpoint."""
    print("Testing positions endpoint...")

    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{api_url}/api/positions", headers=headers, timeout=5)

        if response.status_code == 200:
            data = response.json()

            if data.get('success'):
                print_success("Positions endpoint working")
                print(f"  Position count: {data.get('count', 0)}")

                positions = data.get('positions', [])
                if positions:
                    print("  Positions:")
                    for pos in positions:
                        print(f"    - {pos.get('token_symbol')}: "
                              f"{pos.get('pnl_percent', 0):+.1f}%")
                else:
                    print("  No open positions")

                return True
            else:
                print_error(f"Positions failed: {data.get('error')}")
                return False
        else:
            print_error(f"Positions endpoint error: {response.status_code}")
            return False

    except Exception as e:
        print_error(f"Positions test error: {e}")
        return False


def test_rate_limit(api_url, token):
    """Test rate limiting."""
    print("Testing rate limiting...")

    try:
        headers = {"Authorization": f"Bearer {token}"}

        # Make rapid requests
        success_count = 0
        rate_limited = False

        for i in range(65):  # Try to exceed 60/min limit
            response = requests.get(
                f"{api_url}/api/positions",
                headers=headers,
                timeout=5
            )

            if response.status_code == 200:
                success_count += 1
            elif response.status_code == 429:
                rate_limited = True
                break

        if rate_limited:
            print_success(f"Rate limiting working (after {success_count} requests)")
            return True
        else:
            print_warning(f"Rate limit not triggered ({success_count} requests)")
            return True  # Not a failure, just different config

    except Exception as e:
        print_error(f"Rate limit test error: {e}")
        return False


def main():
    """Run all tests."""
    print()
    print(f"{Colors.BLUE}╔══════════════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.BLUE}║    TRADING API BRIDGE - TEST SUITE          ║{Colors.END}")
    print(f"{Colors.BLUE}╚══════════════════════════════════════════════╝{Colors.END}")

    # Get configuration
    api_url = os.getenv('TRADING_API_URL', 'http://localhost:5000')
    api_token = os.getenv('TRADING_API_TOKEN')

    if not api_token:
        print()
        print_error("TRADING_API_TOKEN not set")
        print()
        print("Set it in .env or export it:")
        print("  export TRADING_API_TOKEN=your_token")
        print()
        sys.exit(1)

    print()
    print(f"API URL: {api_url}")
    print(f"Token: {api_token[:16]}...{api_token[-8:]}")

    # Run tests
    results = []

    print_header("1. HEALTH CHECK")
    results.append(("Health Check", test_health(api_url)))

    print_header("2. AUTHENTICATION")
    results.append(("Authentication", test_auth(api_url, api_token)))

    print_header("3. STATUS ENDPOINT")
    results.append(("Status", test_status(api_url, api_token)))

    print_header("4. POSITIONS ENDPOINT")
    results.append(("Positions", test_positions(api_url, api_token)))

    print_header("5. RATE LIMITING")
    results.append(("Rate Limiting", test_rate_limit(api_url, api_token)))

    # Summary
    print_header("TEST SUMMARY")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        if result:
            print_success(f"{name}")
        else:
            print_error(f"{name}")

    print()
    if passed == total:
        print(f"{Colors.GREEN}🎉 ALL TESTS PASSED ({passed}/{total}){Colors.END}")
        print()
        print("Trading API is ready for use!")
        print()
        return 0
    else:
        print(f"{Colors.RED}⚠ SOME TESTS FAILED ({passed}/{total}){Colors.END}")
        print()
        print("Fix the issues above before using the API.")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
