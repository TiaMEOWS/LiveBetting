"""
Telegram Notification Handler
Sends alerts and status updates to Telegram
"""

import requests
import logging
from typing import Dict, Optional, Any
from datetime import datetime
import config


class TelegramNotifier:
    """Handle all Telegram bot communications"""
    
    def __init__(self):
        self.bot_token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.logger = logging.getLogger(__name__)
    
    def send_message(self, message: str, parse_mode: str = 'HTML', reply_markup: Optional[Dict[Any, Any]] = None, chat_id: Optional[str] = None) -> bool:
        """
        Send message to Telegram chat
        
        Args:
            message: Message text (supports HTML/Markdown)
            parse_mode: 'HTML' or 'Markdown'
        
        Returns:
            True if sent successfully
        """
        url = f"{self.base_url}/sendMessage"
        
        payload = {
            'chat_id': chat_id or self.chat_id,
            'text': message,
            'parse_mode': parse_mode,
            'disable_web_page_preview': True
        }
        
        if reply_markup:
            payload['reply_markup'] = reply_markup
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                self.logger.info("Telegram message sent successfully")
                return True
            else:
                self.logger.error(f"Telegram API error: {response.text}")
                return False
                
        except requests.RequestException as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    def build_pause_keyboard(self):
        """Build inline keyboard with pause/resume controls"""
        if not config.SHOW_PAUSE_BUTTONS:
            return None
        return {
            "inline_keyboard": [[
                {"text": "✅ Oynadım", "callback_data": "PAUSE_NOW"},
                {"text": "⏸️ Duraklat", "callback_data": "PAUSE_NOW"},
                {"text": "▶️ Devam Et", "callback_data": "RESUME"}
            ]]
        }

    def format_match_alert(self, analysis: Dict, scan_number: int) -> str:
        """
        Format match analysis into JSON format (NEW 30-POINT SYSTEM)
        
        Args:
            analysis: Analysis result dictionary
            scan_number: Current scan iteration number
        
        Returns:
            Formatted JSON string
        """
        import json
        
        # Build compact JSON output
        output = {
            "match": f"{analysis['home_team']} vs {analysis['away_team']}",
            "league": analysis['league'],
            "minute": analysis['minute'],
            "score": analysis['score'],
            "confidence": analysis['confidence'],
            "class": analysis.get('classification', 'candidate'),
            "reasons": analysis.get('reasons', []),
            "stats": analysis.get('stats', {}),
            "tags": analysis.get('tags', [])
        }
        
        # Format as pretty JSON for Telegram
        json_str = json.dumps(output, indent=2, ensure_ascii=False)
        
        # Wrap in code block for better formatting in Telegram
        message = f"<pre>{json_str}</pre>"
        
        return message
    
    def send_match_alert(self, analysis: Dict, scan_number: int) -> bool:
        """Send formatted match alert with pause controls"""
        message = self.format_match_alert(analysis, scan_number)
        return self.send_message(message, reply_markup=self.build_pause_keyboard())
    
    def send_duplicate_skip_message(self, match_info: str, next_scan_minutes: int = 5) -> bool:
        """
        Send notification that match was skipped (duplicate)
        
        Args:
            match_info: Brief match description
            next_scan_minutes: Minutes until next scan
        """
        message = f"""✅ <b>Already analyzed:</b> {match_info}
Skipping duplicate - Next scan in {next_scan_minutes}:00"""
        
        return self.send_message(message)
    
    def send_scan_summary(self, scan_number: int, matches_found: int, 
                         matches_qualified: int, duplicates_skipped: int) -> bool:
        """
        Send periodic scan summary
        
        Args:
            scan_number: Current scan number
            matches_found: Total live matches in target window
            matches_qualified: Matches that passed analysis
            duplicates_skipped: Matches skipped as duplicates
        """
        current_time = datetime.utcnow().strftime('%H:%M UTC')
        
        message = f"""📋 <b>Scan Summary #{scan_number}</b> | {current_time}

Live matches (60-72'): {matches_found}
Qualified: {matches_qualified}
Duplicates skipped: {duplicates_skipped}

⏰ Next scan: {(datetime.utcnow().minute // 5 * 5 + 5) % 60:02d} UTC
"""
        
        return self.send_message(message)
    
    def send_api_quota_warning(self, requests_remaining: int, usage_stats: Dict) -> bool:
        """
        Send warning when API quota is running low
        
        Args:
            requests_remaining: Requests left for the day
            usage_stats: Full usage statistics
        """
        message = f"""⚠️ <b>API Quota Warning</b>

Remaining today: {requests_remaining}/{config.DAILY_REQUEST_LIMIT}
Used this hour: {usage_stats.get('requests_this_hour', 0)}/{config.HOURLY_REQUEST_BUDGET}

System will throttle requests to preserve quota.
"""
        
        return self.send_message(message)
    
    def send_system_status(self, uptime_hours: float, total_scans: int, 
                          total_alerts: int, api_stats: Dict) -> bool:
        """
        Send comprehensive system status update
        
        Args:
            uptime_hours: Hours system has been running
            total_scans: Total scans completed
            total_alerts: Total alerts sent
            api_stats: API usage statistics
        """
        message = f"""📊 <b>System Status Report</b>

⏱ Uptime: {uptime_hours:.1f} hours
🔄 Total scans: {total_scans}
🚨 Alerts sent: {total_alerts}

<b>API Usage</b>
• Today: {api_stats.get('requests_today', 0)}/{config.DAILY_REQUEST_LIMIT}
• This hour: {api_stats.get('requests_this_hour', 0)}/{config.HOURLY_REQUEST_BUDGET}
• Remaining: {api_stats.get('daily_remaining', 0)}

System operating normally ✅
"""
        
        return self.send_message(message)
    
    def send_error_notification(self, error_type: str, error_message: str) -> bool:
        """
        Send error notification for critical issues
        
        Args:
            error_type: Type of error (API, Network, Analysis, etc.)
            error_message: Detailed error description
        """
        message = f"""❌ <b>System Error</b>

Type: {error_type}
Details: {error_message}

Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
        
        return self.send_message(message)
    
    def send_startup_notification(self) -> bool:
        """Send notification when system starts"""
        message = f"""🚀 <b>Live Betting System Started</b>

<b>NEW 30-POINT SCORING SYSTEM (S1-S5)</b>
Min Score Required: {config.REQUIRED_SCORE}/{config.MAX_TOTAL_SCORE}
Scan interval: {config.BASE_SCAN_INTERVAL}s
Target window: {config.MIN_MINUTE}-{config.MAX_MINUTE} minutes
Extended window: {config.MIN_MINUTE_EXTENDED}-{config.MAX_MINUTE_EXTENDED} minutes
Allowed scores: 0-0, 1-0, 0-1, 1-1, 2-0, 0-2, 2-1, 1-2

Daily quota: {config.DAILY_REQUEST_LIMIT} requests

System initialized successfully ✅
{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
        
        return self.send_message(message)
