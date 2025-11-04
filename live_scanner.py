"""
24/7 Live Match Scanner with Dynamic Frequency Adjustment
Continuously scans for qualifying matches with intelligent throttling
"""

import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict
import config
from api_client import APIFootballClient
from match_analyzer import MatchAnalyzer
from match_tracker import MatchTracker
from telegram_notifier import TelegramNotifier
from runtime_state import PAUSE_STATE


class LiveScanner:
    """Main 24/7 scanning engine with adaptive frequency"""
    
    def __init__(self):
        self.api_client = APIFootballClient()
        self.analyzer = MatchAnalyzer(self.api_client)
        self.tracker = MatchTracker()
        self.notifier = TelegramNotifier()
        self.logger = logging.getLogger(__name__)
        
        # Scanning state
        self.scan_count = 0
        self.alerts_sent = 0
        self.start_time = datetime.now()
        self.last_cleanup = datetime.now()
        self.last_status_report = datetime.now()
        self.last_limit_check = datetime.now()
        self.limit_exhausted_notified = False
        self.system_status = "ÇALIŞIYOR"  # Track system status
    
    def is_peak_hours(self) -> bool:
        """
        Determine if current time is peak football hours
        Peak: 08:00 - 01:00 UTC (next day)
        """
        current_hour = datetime.utcnow().hour
        
        # Peak hours: 08:00 to 01:00 (next day)
        if config.PEAK_HOURS_START <= current_hour or current_hour < config.PEAK_HOURS_END:
            return True
        
        return False
    
    def calculate_scan_interval(self, live_matches_count: int) -> int:
        """
        Dynamically calculate scan interval based on:
        - API quota remaining (PRIORITY)
        - Time of day (peak vs off-peak)
        - Number of live matches
        
        Returns:
            Scan interval in seconds
        """
        api_stats = self.api_client.get_usage_stats()
        remaining_daily = api_stats.get('daily_remaining', 0)
        
        # SMART SCANNING: Adjust based on remaining quota
        if remaining_daily < 1000:
            # Low quota - conservative scanning (10 min)
            self.logger.warning(f"Low API quota ({remaining_daily}), extending scan interval to 10 minutes")
            return 600  # 10 minutes
        elif remaining_daily < config.EMERGENCY_BUFFER:
            # Critical quota - emergency mode (15 min)
            self.logger.warning("Emergency throttling: low API quota")
            return 900  # 15 minutes
        else:
            # Normal quota - use base interval (60 seconds)
            return config.BASE_SCAN_INTERVAL
    
    def filter_matches_in_window(self, live_matches: List[Dict]) -> List[Dict]:
        """
        Filter matches within target time window
        - Primary: 60-72 minutes
        - Extended: 58-75 minutes (when low traffic)
        
        Args:
            live_matches: All live matches from API
        
        Returns:
            Filtered list of matches in target window
        """
        filtered = []
        primary_matches = []
        extended_matches = []
        
        for match in live_matches:
            fixture = match.get('fixture', {})
            status = fixture.get('status', {})
            elapsed = status.get('elapsed', 0)
            
            # Primary window
            if config.MIN_MINUTE <= elapsed <= config.MAX_MINUTE:
                primary_matches.append(match)
            # Extended window (low traffic fallback)
            elif config.MIN_MINUTE_EXTENDED <= elapsed <= config.MAX_MINUTE_EXTENDED:
                extended_matches.append(match)
        
        # Use primary first, extend if low traffic
        filtered = primary_matches
        if len(primary_matches) < 5:  # Low traffic threshold
            filtered.extend(extended_matches)
            if extended_matches:
                self.logger.info(f"Low traffic mode: Extended to {config.MIN_MINUTE_EXTENDED}-{config.MAX_MINUTE_EXTENDED}'")
        
        return filtered
    
    def process_match(self, fixture: Dict) -> bool:
        """
        Process a single match through analysis pipeline
        
        Args:
            fixture: Match fixture data
        
        Returns:
            True if alert was sent, False otherwise
        """
        try:
            fixture_id = fixture.get('fixture', {}).get('id')
            teams = fixture.get('teams', {})
            home_team = teams.get('home', {}).get('name', 'Unknown')
            away_team = teams.get('away', {}).get('name', 'Unknown')
            minute = fixture.get('fixture', {}).get('status', {}).get('elapsed', 0)
            
            # Validate fixture ID
            if not fixture_id:
                self.logger.debug("Invalid fixture ID, skipping")
                return False
            
            # Check for duplicate
            if self.tracker.is_already_alerted(fixture_id):
                match_desc = f"{home_team} vs {away_team} ({minute}')"
                self.logger.info(f"Skipping duplicate: {match_desc}")
                return False
            
            # Analyze match
            self.logger.info(f"Analyzing: {home_team} vs {away_team} ({minute}')")
            analysis = self.analyzer.analyze_match(fixture)
            
            if not analysis:
                self.logger.debug(f"Match {fixture_id} did not qualify")
                return False
            
            # Match qualifies - send alert
            self.logger.info(f"Match qualified: {home_team} vs {away_team}")
            
            if self.notifier.send_match_alert(analysis, self.scan_count):
                # Track this match to prevent duplicates
                match_info = {
                    'home_team': home_team,
                    'away_team': away_team,
                    'minute': minute,
                    'score': analysis.get('score', '0-0'),
                    'league': analysis.get('league', 'Unknown'),
                }
                self.tracker.add_alerted_match(fixture_id, match_info)
                self.alerts_sent += 1
                return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error processing match: {str(e)}", exc_info=True)
            return False
    
    def perform_scan(self) -> Dict:
        """
        Perform a single scan cycle with request prioritization:
        1. Fetch live matches (1 request)
        2. Only analyze matches in 60-72 min window
        3. Skip duplicates (duplicate protection)
        
        Returns:
            Scan results summary
        """
        self.scan_count += 1
        self.logger.info(f"Starting scan #{self.scan_count} | Status: {self.system_status}")
        
        # Get all live matches
        live_matches = self.api_client.get_live_matches()
        
        if not live_matches or len(live_matches) == 0:
            self.logger.info("No live matches found")
            return {
                'matches_found': 0,
                'matches_qualified': 0,
                'duplicates_skipped': 0,
            }
        
        # Filter to target window
        target_matches = self.filter_matches_in_window(live_matches)
        self.logger.info(f"Found {len(target_matches)} matches in {config.MIN_MINUTE}-{config.MAX_MINUTE}' window")
        
        # Process each match
        qualified_count = 0
        duplicate_count = 0
        
        for match in target_matches:
            fixture_id = match.get('fixture', {}).get('id')
            
            # Check API quota before processing
            if not self.api_client.usage_tracker.can_make_request():
                self.logger.warning("API quota exhausted, skipping remaining matches")
                break
            
            if self.tracker.is_already_alerted(fixture_id):
                duplicate_count += 1
            else:
                if self.process_match(match):
                    qualified_count += 1
        
        # Check API quota and send warning/notification if needed
        api_stats = self.api_client.get_usage_stats()
        remaining = api_stats.get('daily_remaining', 0)
        
        # Advanced warning at 1000 requests remaining
        if remaining <= 1000 and remaining > 500 and (datetime.now() - self.last_limit_check).total_seconds() > 600:
            hours_left = remaining / 100  # Rough estimate
            warning_msg = f"⚠️ <b>API LIMIT YAKLAŞTI</b>\n\nKalan Request: {remaining}\nTahmini Tükenme: {hours_left:.0f} saat\nÖnlem: Tarama aralığı 10 dakikaya çıkarıldı\n\nSistem akıllı tasarruf moduna geçti."
            self.notifier.send_message(warning_msg)
            self.last_limit_check = datetime.now()
        
        # Send warning at 50 requests remaining
        if remaining <= 50 and remaining > 0 and not self.api_client.usage_tracker.limit_warning_sent:
            warning_msg = f"⚠️ <b>API LIMIT UYARISI</b>\n\nKalan Request: {remaining}\nSon {remaining} request kaldı!\n\nSistem yakında duracak."
            self.notifier.send_message(warning_msg)
        
        # Send notification when limit is exhausted
        if remaining <= 0 and not self.limit_exhausted_notified:
            self.limit_exhausted_notified = True
            now_utc = datetime.utcnow()
            midnight_utc = datetime(now_utc.year, now_utc.month, now_utc.day) + timedelta(days=1)
            time_until_reset = midnight_utc - now_utc
            hours_left = int(time_until_reset.total_seconds() // 3600)
            minutes_left = int((time_until_reset.total_seconds() % 3600) // 60)
            
            exhausted_msg = f"🛑 <b>API LIMIT DOLDU</b>\n\nSaat 00:00 UTC'ye kadar sistem duraklatıldı\nKalan Süre: {hours_left} saat {minutes_left} dakika\n\nDurum: DURDU\nSistem otomatik olarak reset'te devam edecek."
            self.notifier.send_message(exhausted_msg)
        
        # Check if limit was reset (after midnight UTC)
        if remaining > 7000 and self.limit_exhausted_notified:
            self.limit_exhausted_notified = False
            reset_msg = f"✅ <b>API LIMIT SIFIRLANDI</b>\n\nYeni Request: 7,500\nSistem otomatik olarak yeniden başlatıldı\nDurum: ÇALIŞIYOR\nİlk tarama: {datetime.utcnow().strftime('%H:%M UTC')}\n\nSistem normal operasyona devam ediyor."
            self.notifier.send_message(reset_msg)
        
        # Emergency buffer warning
        if remaining < config.EMERGENCY_BUFFER and remaining > config.EMERGENCY_BUFFER * 0.5:
            self.notifier.send_api_quota_warning(remaining, api_stats)
        
        return {
            'matches_found': len(target_matches),
            'matches_qualified': qualified_count,
            'duplicates_skipped': duplicate_count,
        }
    
    def periodic_maintenance(self):
        """
        Perform periodic maintenance tasks:
        - Cleanup old matches
        - Send status reports
        - Check API limits
        """
        now = datetime.now()
        
        # Check API limit every 5 minutes
        if (now - self.last_limit_check).total_seconds() > 300:  # 5 minutes
            api_stats = self.api_client.get_usage_stats()
            remaining = api_stats.get('daily_remaining', 0)
            
            # Log current usage
            self.logger.info(f"API Status: {remaining}/{config.DAILY_REQUEST_LIMIT} remaining")
            self.last_limit_check = now
        
        # Daily cleanup of old tracked matches
        if (now - self.last_cleanup).total_seconds() > 86400:  # 24 hours
            cleaned = self.tracker.cleanup_old_matches()
            self.logger.info(f"Cleaned {cleaned} old matches from tracker")
            self.last_cleanup = now
        
        # Hourly status report
        if (now - self.last_status_report).total_seconds() > 3600:  # 1 hour
            uptime = (now - self.start_time).total_seconds() / 3600
            api_stats = self.api_client.get_usage_stats()
            
            self.notifier.send_system_status(
                uptime_hours=uptime,
                total_scans=self.scan_count,
                total_alerts=self.alerts_sent,
                api_stats=api_stats
            )
            self.last_status_report = now
    
    def run(self):
        """
        Main 24/7 scanning loop
        Runs continuously with adaptive frequency
        """
        self.logger.info("Starting 24/7 Live Betting Scanner")
        self.notifier.send_startup_notification()
        
        scan_no = 0
        pause_message_sent = False
        try:
            while True:
                # 🔒 PAUSE GUARD
                while PAUSE_STATE.is_paused():
                    if not pause_message_sent:
                        self.logger.info("Sistem duraklatıldı. Devam et komutu bekleniyor... (API istekleri durdu)")
                        pause_message_sent = True
                    # Wait for 30 seconds before checking again to reduce CPU usage
                    # but still be responsive to resume commands
                    time.sleep(30)
                
                # Reset pause message flag when system resumes
                if pause_message_sent:
                    self.logger.info("Sistem devam ediyor. Tarama işlemine devam ediliyor...")
                    pause_message_sent = False
                    
                # 🔓 Normal analiz akışı
                scan_no += 1
                self.logger.info(f"Starting scan #{scan_no} | Status: ÇALIŞIYOR")
                
                try:
                    # Check if API limit is exhausted
                    api_stats = self.api_client.get_usage_stats()
                    remaining = api_stats.get('daily_remaining', 0)
                    
                    if remaining <= 0:
                        # Limit exhausted - update status and wait until midnight UTC
                        if self.system_status != "DURDU":
                            self.system_status = "DURDU"
                            self.logger.critical("System status: DURDU - API limit exhausted")
                        
                        now_utc = datetime.utcnow()
                        midnight_utc = datetime(now_utc.year, now_utc.month, now_utc.day) + timedelta(days=1)
                        wait_seconds = (midnight_utc - now_utc).total_seconds()
                        
                        self.logger.warning(f"API limit exhausted. Waiting {wait_seconds/3600:.1f} hours until reset")
                        time.sleep(min(wait_seconds, 300))  # Check every 5 minutes
                        continue
                    
                    # Check if status should be restored
                    if self.system_status == "DURDU" and remaining > 0:
                        self.system_status = "ÇALIŞIYOR"
                        self.logger.info("System status: ÇALIŞIYOR - API limit restored")
                    
                    # Perform scan
                    scan_results = self.perform_scan()
                    
                    # Periodic maintenance
                    self.periodic_maintenance()
                    
                    # Calculate next scan interval
                    next_interval = self.calculate_scan_interval(
                        scan_results['matches_found']
                    )
                    
                    self.logger.info(
                        f"Scan complete. Found: {scan_results['matches_found']}, "
                        f"Qualified: {scan_results['matches_qualified']}, "
                        f"Duplicates: {scan_results['duplicates_skipped']}. "
                        f"Next scan in {next_interval}s"
                    )
                    
                    # Wait until next scan
                    time.sleep(next_interval)
                    
                except Exception as e:
                    self.logger.error(f"Error in scan cycle: {str(e)}", exc_info=True)
                    self.notifier.send_error_notification("Scan Error", str(e))
                    
                    # Wait before retrying
                    time.sleep(60)
                    
        except KeyboardInterrupt:
            self.logger.info("Scanner stopped by user")
            self.notifier.send_message("🛑 System stopped by user")
        
        except Exception as e:
            self.logger.critical(f"Critical system error: {str(e)}", exc_info=True)
            self.notifier.send_error_notification("Critical System Error", str(e))
