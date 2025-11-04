"""
System Test Script - Verify all components are working
Run this before starting the 24/7 system
"""

import sys
from logger_config import setup_logging
from api_client import APIFootballClient
from telegram_notifier import TelegramNotifier
from match_tracker import MatchTracker


def test_logging():
    """Test logging system"""
    print("Testing logging system...")
    logger = setup_logging()
    logger.info("Test log entry")
    print("✓ Logging system working")
    return True


def test_telegram():
    """Test Telegram bot connection"""
    print("\nTesting Telegram bot...")
    notifier = TelegramNotifier()
    
    message = """🧪 <b>System Test</b>

This is a test message from your Live Betting Analysis System.

If you're seeing this, the Telegram integration is working correctly! ✅

The system is ready to start scanning for matches.
"""
    
    success = notifier.send_message(message)
    if success:
        print("✓ Telegram bot working - check your Telegram!")
        return True
    else:
        print("✗ Telegram bot failed - check your bot token and chat ID")
        return False


def test_api_client():
    """Test API-Football connection"""
    print("\nTesting API-Football connection...")
    client = APIFootballClient()
    
    # Get API usage stats (doesn't consume request)
    stats = client.get_usage_stats()
    print(f"  Daily quota: {stats['daily_remaining']}/{7500}")
    print(f"  Hourly quota: {stats['hourly_remaining']}/{312}")
    
    # Try to get live matches
    print("  Fetching live matches...")
    try:
        live_matches = client.get_live_matches()
        
        if live_matches is not None:
            print(f"✓ API-Football working - Found {len(live_matches)} live matches")
            if len(live_matches) > 0:
                print(f"  Sample match: {live_matches[0].get('teams', {}).get('home', {}).get('name', 'N/A')} vs {live_matches[0].get('teams', {}).get('away', {}).get('name', 'N/A')}")
            return True
        else:
            print("✗ API-Football connection failed - check your API key")
            return False
    except Exception as e:
        print(f"✗ API-Football error: {str(e)}")
        return False


def test_match_tracker():
    """Test match tracking database"""
    print("\nTesting match tracking system...")
    tracker = MatchTracker()
    
    # Test adding a match
    test_match = {
        'home_team': 'Test Home',
        'away_team': 'Test Away',
        'minute': 65,
        'score': '1-1',
        'league': 'Test League'
    }
    
    tracker.add_alerted_match(999999, test_match)
    
    # Test duplicate detection
    is_duplicate = tracker.is_already_alerted(999999)
    
    if is_duplicate:
        print("✓ Match tracker working - Duplicate detection functional")
        
        # Get statistics
        stats = tracker.get_statistics()
        print(f"  Tracked matches: {stats['total_tracked']}")
        print(f"  Daily alerts: {stats['daily_alerts']}")
        return True
    else:
        print("✗ Match tracker failed")
        return False


def main():
    """Run all system tests"""
    print("="*60)
    print("24/7 LIVE BETTING ANALYSIS SYSTEM - COMPONENT TESTS")
    print("="*60)
    
    results = []
    
    # Run tests
    results.append(("Logging System", test_logging()))
    results.append(("Match Tracker", test_match_tracker()))
    results.append(("API-Football", test_api_client()))
    results.append(("Telegram Bot", test_telegram()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status} - {name}")
    
    all_passed = all(result[1] for result in results)
    
    print("="*60)
    if all_passed:
        print("\n✅ ALL TESTS PASSED - System is ready!")
        print("\nYou can now start the 24/7 scanner:")
        print("  → Run: python main.py")
        print("  → Or double-click: start.bat")
    else:
        print("\n❌ SOME TESTS FAILED - Fix issues before starting")
        print("\nCheck:")
        print("  • API key in config.py")
        print("  • Telegram bot token in config.py")
        print("  • Internet connection")
    print()


if __name__ == "__main__":
    main()
