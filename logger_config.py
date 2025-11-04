"""
Logging Configuration for 24/7 Operation
Comprehensive logging with file rotation and monitoring
"""

import logging
import logging.handlers
import os
from datetime import datetime
import config


def setup_logging():
    """
    Configure logging with both file and console handlers
    Includes rotating file handler to prevent excessive log growth
    """
    # Create logs directory if it doesn't exist
    log_dir = os.path.dirname(config.LOG_FILE) or '.'
    if log_dir != '.' and not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Root logger configuration
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Clear any existing handlers
    logger.handlers = []
    
    # Format for log messages
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler - for immediate feedback
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Rotating file handler - prevents log files from growing too large
    # Max 10MB per file, keep 5 backup files
    file_handler = logging.handlers.RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Error-specific file handler
    error_handler = logging.handlers.RotatingFileHandler(
        'errors.log',
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)
    
    logger.info("=" * 80)
    logger.info(f"Logging initialized at {datetime.now().isoformat()}")
    logger.info("=" * 80)
    
    return logger


class ErrorMonitor:
    """
    Monitor and track errors for alerting
    Prevents alert spam while ensuring critical errors are reported
    """
    
    def __init__(self, notifier):
        self.notifier = notifier
        self.error_counts = {}
        self.last_alert_time = {}
        self.logger = logging.getLogger(__name__)
        
        # Thresholds
        self.alert_threshold = 3  # Alert after 3 occurrences
        self.alert_cooldown = 3600  # 1 hour cooldown between same error alerts
    
    def log_error(self, error_type: str, error_message: str, send_alert: bool = True):
        """
        Log error and optionally send Telegram alert
        
        Args:
            error_type: Category of error (API, Network, Analysis, etc.)
            error_message: Detailed error description
            send_alert: Whether to send Telegram notification
        """
        self.logger.error(f"{error_type}: {error_message}")
        
        if not send_alert:
            return
        
        # Track error occurrence
        error_key = f"{error_type}:{error_message}"
        self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1
        
        # Check if should alert
        should_alert = False
        now = datetime.now()
        
        if self.error_counts[error_key] >= self.alert_threshold:
            # Check cooldown
            if error_key not in self.last_alert_time:
                should_alert = True
            else:
                time_since_last = (now - self.last_alert_time[error_key]).total_seconds()
                if time_since_last > self.alert_cooldown:
                    should_alert = True
        
        if should_alert:
            self.notifier.send_error_notification(error_type, error_message)
            self.last_alert_time[error_key] = now
            self.error_counts[error_key] = 0  # Reset counter
    
    def log_warning(self, warning_type: str, warning_message: str):
        """Log warning without sending alert"""
        self.logger.warning(f"{warning_type}: {warning_message}")
    
    def get_error_summary(self) -> dict:
        """Get summary of recent errors"""
        return {
            'total_error_types': len(self.error_counts),
            'error_counts': dict(self.error_counts),
            'recent_alerts': len(self.last_alert_time)
        }
