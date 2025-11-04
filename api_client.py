"""
API-Football Client with Rate Limiting and Optimization
Handles all API interactions with intelligent request management
"""

import requests
import time
import logging
from typing import Dict, List, Optional
from datetime import datetime
import config
from runtime_state import PAUSE_STATE


class APIUsageTracker:
    """Track API usage to stay within daily limits"""
    
    def __init__(self):
        self.requests_today = 0
        self.requests_this_hour = 0
        self.last_reset = datetime.now()
        self.last_hour_reset = datetime.now()
        self.limit_warning_sent = False  # Track if warning was sent
        self.system_paused = False  # Track if system is paused due to limit
    
    def reset_if_needed(self):
        """Reset counters at day/hour boundaries"""
        now = datetime.now()
        
        # Reset daily counter at midnight UTC
        if now.date() > self.last_reset.date():
            self.requests_today = 0
            self.last_reset = now
            self.limit_warning_sent = False
            self.system_paused = False
            logging.info("✅ Daily API counter reset - 7,500 requests available")
        
        # Reset hourly counter
        if (now - self.last_hour_reset).total_seconds() >= 3600:
            self.requests_this_hour = 0
            self.last_hour_reset = now
    
    def can_make_request(self) -> bool:
        """Check if we can make another request without exceeding limits"""
        self.reset_if_needed()
        
        remaining_daily = config.DAILY_REQUEST_LIMIT - self.requests_today
        
        # Check if limit is completely exhausted
        if remaining_daily <= 0:
            if not self.system_paused:
                self.system_paused = True
                logging.critical("🛑 API LIMIT EXHAUSTED! System paused until 00:00 UTC")
            return False
        
        # Send warning when approaching limit (50 requests left)
        if remaining_daily <= 50 and not self.limit_warning_sent:
            self.limit_warning_sent = True
            logging.warning(f"⚠️ API LIMIT WARNING: Only {remaining_daily} requests remaining!")
        
        # Emergency buffer check
        if remaining_daily <= config.EMERGENCY_BUFFER:
            logging.warning(f"Approaching daily limit: {remaining_daily} requests left")
            return remaining_daily > config.EMERGENCY_BUFFER * 0.5
        
        return True  # Always allow if daily quota is OK
    
    def record_request(self):
        """Increment usage counters"""
        self.requests_today += 1
        self.requests_this_hour += 1
    
    def get_usage_stats(self) -> Dict:
        """Get current usage statistics"""
        self.reset_if_needed()
        return {
            'requests_today': self.requests_today,
            'requests_this_hour': self.requests_this_hour,
            'daily_remaining': config.DAILY_REQUEST_LIMIT - self.requests_today,
            'hourly_remaining': config.HOURLY_REQUEST_BUDGET - self.requests_this_hour,
        }


class APIFootballClient:
    """Client for API-Football with retry logic and rate limiting"""
    
    def __init__(self):
        self.base_url = config.API_FOOTBALL_BASE_URL
        self.headers = {
            'x-apisports-key': config.API_FOOTBALL_KEY
        }
        self.usage_tracker = APIUsageTracker()
        self.logger = logging.getLogger(__name__)
    
    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """
        Make API request with retry logic and error handling
        
        Args:
            endpoint: API endpoint (e.g., '/fixtures')
            params: Query parameters
        
        Returns:
            JSON response or None on failure
        """
        # 🔒 PAUSE CHECK - don't make API requests when paused
        if PAUSE_STATE.is_paused():
            self.logger.debug("API request blocked: system is paused")
            return None
            
        if not self.usage_tracker.can_make_request():
            self.logger.warning("API request blocked: quota limit approaching")
            return None
        
        url = f"{self.base_url}{endpoint}"
        
        for attempt in range(config.MAX_RETRIES):
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=config.REQUEST_TIMEOUT
                )
                
                self.usage_tracker.record_request()
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        return data
                    except ValueError as e:
                        self.logger.error(f"Invalid JSON response: {e}")
                        return None
                
                elif response.status_code == 429:  # Rate limited
                    wait_time = config.RETRY_BACKOFF_FACTOR ** (attempt + 1)
                    self.logger.warning(f"Rate limited, waiting {wait_time}s")
                    time.sleep(wait_time)
                    
                else:
                    self.logger.error(f"API error {response.status_code}: {response.text}")
                    return None
                    
            except requests.Timeout:
                self.logger.error(f"Request timeout on attempt {attempt + 1}")
                if attempt < config.MAX_RETRIES - 1:
                    time.sleep(config.RETRY_BACKOFF_FACTOR ** attempt)
                    
            except requests.RequestException as e:
                self.logger.error(f"Request failed: {str(e)}")
                return None
        
        return None
    
    def get_live_matches(self) -> List[Dict]:
        """
        Fetch all currently live matches
        
        Returns:
            List of live match dictionaries
        """
        response = self._make_request('/fixtures', {'live': 'all'})
        
        if response and response.get('response'):
            return response['response']
        
        return []
    
    def get_match_statistics(self, fixture_id: int) -> Optional[Dict]:
        """
        Get detailed statistics for a specific match
        
        Args:
            fixture_id: Match ID
        
        Returns:
            Statistics dictionary or None
        """
        response = self._make_request('/fixtures/statistics', {'fixture': fixture_id})
        
        if response and response.get('response'):
            return response['response']
        
        return None
    
    def get_match_events(self, fixture_id: int) -> List[Dict]:
        """
        Get match events (goals, cards, substitutions)
        
        Args:
            fixture_id: Match ID
        
        Returns:
            List of events
        """
        response = self._make_request('/fixtures/events', {'fixture': fixture_id})
        
        if response and response.get('response'):
            return response['response']
        
        return []
    
    def get_h2h_matches(self, team1_id: int, team2_id: int, last: int = 5) -> List[Dict]:
        """
        Get head-to-head history between two teams
        
        Args:
            team1_id: First team ID
            team2_id: Second team ID
            last: Number of recent H2H matches
        
        Returns:
            List of H2H matches
        """
        response = self._make_request('/fixtures/headtohead', {
            'h2h': f"{team1_id}-{team2_id}",
            'last': last
        })
        
        if response and response.get('response'):
            return response['response']
        
        return []
    
    def get_team_form(self, team_id: int, last: int = 5) -> List[Dict]:
        """
        Get team's recent form (last N matches)
        
        Args:
            team_id: Team ID
            last: Number of recent matches
        
        Returns:
            List of recent matches
        """
        response = self._make_request('/fixtures', {
            'team': team_id,
            'last': last
        })
        
        if response and response.get('response'):
            return response['response']
        
        return []
    
    def get_usage_stats(self) -> Dict:
        """Get API usage statistics"""
        return self.usage_tracker.get_usage_stats()
