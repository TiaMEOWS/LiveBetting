"""
Match Tracking Database for Duplicate Prevention
Maintains persistent storage of analyzed matches
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
import config


class MatchTracker:
    def __init__(self, db_file: str = config.DATABASE_FILE):
        self.db_file = db_file
        self.alerted_matches = self._load_database()
        
    def _load_database(self) -> Dict:
        """Load match tracking database from file"""
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logging.warning(f"Error loading database: {e}. Starting fresh.")
                return {}
        return {}
    
    def _save_database(self):
        """Persist database to file"""
        try:
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(self.alerted_matches, f, indent=2)
        except IOError as e:
            logging.error(f"Error saving database: {e}")
    
    def is_already_alerted(self, match_id: int) -> bool:
        """
        Check if match was already alerted within the memory window
        Returns True if duplicate, False if new
        """
        match_key = str(match_id)
        
        if match_key not in self.alerted_matches:
            return False
        
        match_data = self.alerted_matches[match_key]
        first_alert = datetime.fromisoformat(match_data['first_alert_time'])
        time_since_alert = datetime.now() - first_alert
        
        # Check if within memory window (24 hours)
        if time_since_alert.total_seconds() < config.MATCH_MEMORY_HOURS * 3600:
            return True
        
        # Expired - can be re-used
        return False
    
    def add_alerted_match(self, match_id: int, match_info: Dict):
        """
        Add a newly alerted match to tracking database
        
        Args:
            match_id: Unique match identifier
            match_info: Dict containing match details (teams, minute, score, etc.)
        """
        match_key = str(match_id)
        
        self.alerted_matches[match_key] = {
            'first_alert_time': datetime.now().isoformat(),
            'match_status': 'active',
            're_analysis_allowed': False,
            'home_team': match_info.get('home_team', ''),
            'away_team': match_info.get('away_team', ''),
            'minute': match_info.get('minute', 0),
            'score': match_info.get('score', ''),
            'league': match_info.get('league', ''),
        }
        
        self._save_database()
    
    def update_match_status(self, match_id: int, status: str):
        """Update match status (active/completed)"""
        match_key = str(match_id)
        if match_key in self.alerted_matches:
            self.alerted_matches[match_key]['match_status'] = status
            self._save_database()
    
    def cleanup_old_matches(self):
        """
        Remove matches older than memory window to free storage
        Run daily to maintain database efficiency
        """
        current_time = datetime.now()
        expired_matches = []
        
        for match_id, match_data in self.alerted_matches.items():
            first_alert = datetime.fromisoformat(match_data['first_alert_time'])
            age_hours = (current_time - first_alert).total_seconds() / 3600
            
            if age_hours > config.MATCH_MEMORY_HOURS:
                expired_matches.append(match_id)
        
        for match_id in expired_matches:
            del self.alerted_matches[match_id]
        
        if expired_matches:
            self._save_database()
        
        return len(expired_matches)
    
    def get_match_details(self, match_id: int) -> Optional[Dict]:
        """Retrieve stored match details"""
        match_key = str(match_id)
        return self.alerted_matches.get(match_key)
    
    def get_daily_alert_count(self) -> int:
        """Get number of alerts sent in last 24 hours"""
        current_time = datetime.now()
        count = 0
        
        for match_data in self.alerted_matches.values():
            first_alert = datetime.fromisoformat(match_data['first_alert_time'])
            age_hours = (current_time - first_alert).total_seconds() / 3600
            
            if age_hours <= 24:
                count += 1
        
        return count
    
    def get_statistics(self) -> Dict:
        """Get database statistics for monitoring"""
        total_tracked = len(self.alerted_matches)
        active_matches = sum(1 for m in self.alerted_matches.values() 
                           if m['match_status'] == 'active')
        completed_matches = sum(1 for m in self.alerted_matches.values() 
                              if m['match_status'] == 'completed')
        
        return {
            'total_tracked': total_tracked,
            'active_matches': active_matches,
            'completed_matches': completed_matches,
            'daily_alerts': self.get_daily_alert_count()
        }
