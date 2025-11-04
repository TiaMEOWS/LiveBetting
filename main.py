"""
24/7 Live Betting Analysis System - Main Entry Point
Professional football betting analysis for Telegram bot
"""

import sys
import signal
import threading
from logger_config import setup_logging, ErrorMonitor
from live_scanner import LiveScanner
from telegram_notifier import TelegramNotifier
from telegram_controller import polling_loop
import config


def signal_handler(sig, frame):
    """Handle graceful shutdown on CTRL+C"""
    print("\n🛑 Shutting down gracefully...")
    sys.exit(0)


def main():
    """Main application entry point"""
    # Setup logging
    logger = setup_logging()
    logger.info("Initializing 24/7 Live Betting Analysis System")
    
    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start Telegram polling thread
    if config.TELEGRAM_POLLING:
        t = threading.Thread(target=polling_loop, daemon=True)
        t.start()
        logger.info("Telegram polling thread started.")
    
    try:
        # Initialize scanner and start 24/7 operation
        scanner = LiveScanner()
        scanner.run()
        
    except Exception as e:
        logger.critical(f"Fatal error: {str(e)}", exc_info=True)
        
        # Send emergency notification
        try:
            notifier = TelegramNotifier()
            notifier.send_error_notification("Fatal System Error", str(e))
        except:
            pass
        
        sys.exit(1)


if __name__ == "__main__":
    main()
