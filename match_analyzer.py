"""
Match Analysis Engine with Advanced 30-Point Scoring System
Identifies matches with low goal probability using enhanced momentum and psychological analysis
"""

import logging
from typing import Dict, List, Optional, Tuple
import config


class MatchAnalyzer:
    """Advanced match analysis with 30-point scoring system (S1-S5)"""
    
    def __init__(self, api_client):
        self.api_client = api_client
        self.logger = logging.getLogger(__name__)
        self.analysis_cache = {}  # Cache: fixture_id -> {score, minute, last_event, confidence}

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------

    def score_band(self, value: float, bands: List[Tuple[float, int]], default: int = 0) -> int:
        """Return banded score for a metric (lower values earn more points)."""
        for threshold, points in bands:
            if value <= threshold:
                return points
        return default

    def is_shot_event(self, event: Dict) -> bool:
        """Heuristic to detect shot attempts from event feed."""
        event_type = str(event.get('type', '')).lower()
        detail = str(event.get('detail', '')).lower()
        return (
            'shot' in event_type
            or 'shot' in detail
            or 'goal' in detail
            or event_type == 'goal'
        )

    def is_shot_on_target_event(self, event: Dict) -> bool:
        """Detect on-target attempts (goals, clear chances)."""
        detail = str(event.get('detail', '')).lower()
        event_type = str(event.get('type', '')).lower()
        return (
            'goal' in detail
            or 'shot on target' in detail
            or (event_type == 'goal')
            or ('penalty' in detail and 'missed' not in detail)
        )

    def parse_numeric_value(self, value) -> Optional[float]:
        """Safely parse numeric values that may come as strings or percentages."""
        if value in (None, 'N/A'):
            return None

        if isinstance(value, (int, float)):
            return float(value)

        try:
            cleaned = str(value).replace('%', '').strip()
            if not cleaned:
                return None
            return float(cleaned)
        except (TypeError, ValueError):
            return None

    def count_events_in_range(
        self,
        events: List[Dict],
        start_minute: int,
        end_minute: int,
        predicate,
    ) -> int:
        """Count events that satisfy predicate within [start_minute, end_minute]."""
        if not events:
            return 0

        start = max(0, start_minute)
        end = max(start, end_minute)
        total = 0

        for event in events:
            event_minute = event.get('time', {}).get('elapsed')
            if event_minute is None:
                continue
            if start <= event_minute <= end and predicate(event):
                total += 1

        return total

    def calculate_tempo_metrics(self, events: List[Dict], minute: int) -> Dict:
        """Summarise recent tempo/pressure indicators from event feed."""
        window_start = minute - 12
        dangerous_actions = self.count_events_in_range(
            events,
            window_start,
            minute,
            self.is_shot_event,
        )
        pressure_events = self.count_events_in_range(
            events,
            window_start,
            minute,
            lambda e: str(e.get('detail', '')).lower() in ['corner', 'dangerous attack']
            or 'free kick' in str(e.get('detail', '')).lower(),
        )
        cards_recent = self.count_events_in_range(
            events,
            window_start,
            minute,
            lambda e: 'card' in str(e.get('detail', '')).lower(),
        )
        tempo_minutes = max(1, minute - max(0, window_start))

        tempo_index = (dangerous_actions + 0.6 * pressure_events) / tempo_minutes
        xg_slope = self.calculate_xg_slope(events, minute)

        return {
            'window_minutes': tempo_minutes,
            'dangerous_actions': dangerous_actions,
            'pressure_events': pressure_events,
            'cards_recent': cards_recent,
            'tempo_index': round(tempo_index, 3),
            'xg_slope': xg_slope,
        }

    def calculate_risk_index(self, tempo_metrics: Dict) -> float:
        """Aggregate tempo metrics into a 0-1 risk score."""
        tempo_score = min(1.0, tempo_metrics['dangerous_actions'] / max(1, config.RISK_DANGEROUS_ACTIONS_CAP))
        pressure_score = min(1.0, tempo_metrics['pressure_events'] / max(1, config.RISK_PRESSURE_EVENTS_CAP))
        card_score = min(1.0, tempo_metrics['cards_recent'] / max(1, config.RISK_CARD_EVENTS_CAP))
        slope_raw = max(0.0, tempo_metrics['xg_slope'])
        slope_score = min(1.0, slope_raw / max(0.01, config.RISK_SLOPE_CAP))

        risk_index = (
            tempo_score * config.RISK_TEMPO_WEIGHT
            + pressure_score * config.RISK_PRESSURE_WEIGHT
            + card_score * config.RISK_CARD_WEIGHT
            + slope_score * config.RISK_XG_SLOPE_WEIGHT
        )

        return round(min(1.0, risk_index), 3)

    def extract_statistic(self, stats: List[Dict], stat_name: str, team_index: Optional[int] = None) -> Optional[int]:
        """
        Extract specific statistic from API response
        
        Args:
            stats: Statistics array from API
            stat_name: Name of statistic (e.g., 'Total Shots', 'Shots on Goal')
            team_index: 0 for home, 1 for away, None for both
        
        Returns:
            Statistic value or None
        """
        if not stats:
            return None
        
        try:
            if team_index is not None:
                team_stats = stats[team_index].get('statistics', [])
            else:
                # Combine both teams
                total = 0
                for team in stats:
                    team_stats = team.get('statistics', [])
                    for stat in team_stats:
                        if stat.get('type') == stat_name:
                            value = stat.get('value')
                            if value and value != 'N/A':
                                # Handle percentage values
                                str_val = str(value).replace('%', '')
                                int_value = int(str_val) if str_val.isdigit() else 0
                                total += int_value
                return total
            
            for stat in team_stats:
                if stat.get('type') == stat_name:
                    value = stat.get('value')
                    if value and value != 'N/A':
                        str_val = str(value).replace('%', '')
                        return int(str_val) if str_val.isdigit() else 0
        except (IndexError, KeyError, ValueError) as e:
            self.logger.debug(f"Error extracting {stat_name}: {e}")
        
        return None
    
    def calculate_xg_from_stats(self, stats: List[Dict]) -> Tuple[float, float, Tuple[float, float]]:
        """
        Calculate approximate xG from available statistics

        Returns:
            (combined_xg, second_half_xg, (home_xg, away_xg)) tuple
        """
        if not stats or len(stats) < 2:
            return 0.0, 0.0, (0.0, 0.0)

        total_xg = 0.0
        team_xg_values: List[float] = []

        for team_stats in stats:
            team_stat_list = team_stats.get('statistics', [])

            shots_on_target = 0
            total_shots = 0
            team_xg = None

            for stat in team_stat_list:
                stat_type = str(stat.get('type', '')).strip()
                value = stat.get('value')
                numeric_value = self.parse_numeric_value(value)

                if numeric_value is None:
                    continue

                stat_key = stat_type.lower()
                if stat_key in {'expected goals', 'expected_goals', 'xg'}:
                    team_xg = numeric_value
                elif stat_type == 'Shots on Goal':
                    shots_on_target = int(round(numeric_value))
                elif stat_type == 'Total Shots':
                    total_shots = int(round(numeric_value))

            if team_xg is None:
                # xG estimation: shots_on_target * 0.35 + off_target_shots * 0.05
                off_target = max(0, total_shots - shots_on_target)
                team_xg = (shots_on_target * 0.35) + (off_target * 0.05)

            total_xg += team_xg
            team_xg_values.append(round(team_xg, 2))

        if len(team_xg_values) < 2:
            # Fallback: split evenly if we could not resolve each team separately
            even_split = round(total_xg / max(1, len(team_xg_values) or 1), 2)
            while len(team_xg_values) < 2:
                team_xg_values.append(even_split)

        # Second half xG estimate (weighted towards live action)
        second_half_xg = total_xg * 0.35

        return round(total_xg, 2), round(second_half_xg, 2), (team_xg_values[0], team_xg_values[1])

    def calculate_match_score(self, stats: List[Dict], events: List[Dict],
                              goals_data: Dict, minute: int,
                              combined_xg: float, second_half_xg: float,
                              team_xg_split: Tuple[float, float]) -> Tuple[int, Dict, str]:
        """
        Calculate match score based on 30-point system (S1-S5)

        Returns:
            (total_score, score_breakdown, bonus_tag)
        """
        score = 0
        breakdown = {}
        bonus_tag = ""
        penalties = 0  # Penalty points (negative)

        if not stats or len(stats) < 2:
            return 0, breakdown, bonus_tag

        # Event-derived counters for dynamic scoring
        second_half_shots = self.count_events_in_range(events, 45, minute, self.is_shot_event)
        second_half_sot = self.count_events_in_range(events, 45, minute, self.is_shot_on_target_event)
        last_15min_shots = self.count_events_in_range(events, minute - 15, minute, self.is_shot_event)
        second_half_corners = self.count_events_in_range(
            events,
            45,
            minute,
            lambda e: str(e.get('detail', '')).lower() == 'corner',
        )

        # ============ SECTION 1: MATCH-WIDE CRITERIA (Max 9 points) ============

        # 1.1 Total xG ≤2.2 (+3 points)
        xg_points = self.score_band(combined_xg, [(1.6, 3), (1.9, 2), (config.MAX_COMBINED_XG, 1)])
        score += xg_points
        breakdown['total_xg'] = xg_points

        # 1.2 Total shots ≤14 (+2 points)
        total_shots = self.extract_statistic(stats, 'Total Shots') or 0
        total_shots_points = self.score_band(total_shots, [(10, 2), (config.MAX_TOTAL_SHOTS, 1)])
        score += total_shots_points
        breakdown['total_shots'] = total_shots_points

        # 1.3 Total shots on target ≤5 (+2 points)
        shots_on_target = self.extract_statistic(stats, 'Shots on Goal') or 0
        shots_on_target_points = self.score_band(shots_on_target, [(3, 2), (config.MAX_SHOTS_ON_TARGET, 1)])
        score += shots_on_target_points
        breakdown['shots_on_target'] = shots_on_target_points

        # 1.4 Total corners ≤7 (+1 point)
        total_corners = self.extract_statistic(stats, 'Corner Kicks') or 0
        corners_points = self.score_band(total_corners, [(4, 1), (config.MAX_CORNERS, 1)]) if total_corners <= config.MAX_CORNERS else 0
        score += corners_points
        breakdown['corners'] = corners_points

        # 1.5 Possession difference ≤18% (+1 point)
        home_poss = self.extract_statistic(stats, 'Ball Possession', 0) or 50
        away_poss = self.extract_statistic(stats, 'Ball Possession', 1) or 50
        poss_diff = abs(home_poss - away_poss)
        poss_points = self.score_band(poss_diff, [(10, 1), (config.MAX_POSSESSION_DIFF, 1)]) if poss_diff <= config.MAX_POSSESSION_DIFF else 0
        score += poss_points
        breakdown['possession_diff'] = poss_points
        
        # ============ SECTION 2: SECOND HALF CRITERIA (Max 11 points) ============
        
        # 2.1 2nd half xG ≤0.6 (+3 points)
        second_half_xg_points = self.score_band(
            second_half_xg,
            [(0.35, 3), (0.5, 2), (config.MAX_SECOND_HALF_XG, 1)],
        )
        score += second_half_xg_points
        breakdown['second_half_xg'] = second_half_xg_points

        # 2.2 2nd half shots ≤5 (+2 points) - using live events when available
        if second_half_shots == 0 and not events:
            second_half_shots = int(total_shots * 0.45)
        second_half_shots_points = self.score_band(
            second_half_shots,
            [(3, 2), (config.MAX_SECOND_HALF_SHOTS, 1)],
        )
        score += second_half_shots_points
        breakdown['second_half_shots'] = second_half_shots_points

        # 2.3 2nd half shots on target ≤2 (+2 points)
        if second_half_sot == 0 and not events:
            second_half_sot = int(shots_on_target * 0.5)
        second_half_sot_points = self.score_band(
            second_half_sot,
            [(1, 2), (config.MAX_SECOND_HALF_SHOTS_ON_TARGET, 1)],
        )
        score += second_half_sot_points
        breakdown['second_half_sot'] = second_half_sot_points

        # 2.4 Last 15min shots ≤3 (+2 points)
        if last_15min_shots == 0 and not events:
            last_15min_shots = int(total_shots * 0.2)
        last15_points = self.score_band(last_15min_shots, [(2, 2), (3, 1)])
        score += last15_points
        breakdown['last_15min_shots'] = last15_points

        # 2.5 2nd half corners ≤3 (+1 point)
        if second_half_corners == 0 and total_corners and not events:
            second_half_corners = int(total_corners * 0.5)
        second_half_corners_points = 1 if second_half_corners <= config.MAX_SECOND_HALF_CORNERS else 0
        score += second_half_corners_points
        breakdown['second_half_corners'] = second_half_corners_points
        
        # 2.6 2nd half possession diff ≤15% (+1 point)
        if poss_diff <= config.MAX_SECOND_HALF_POSSESSION_DIFF:
            score += 1
            breakdown['second_half_poss_diff'] = 1
        else:
            breakdown['second_half_poss_diff'] = 0
        
        # ============ [NEW S4] MOMENTUM & TEMPO DYNAMICS (Max 5 points) ============
        
        # 4.1 xG slope last 10 minutes ≤ 0 (+2 points)
        xg_slope_last10 = self.calculate_xg_slope(events, minute)
        if xg_slope_last10 <= config.MAX_XG_SLOPE_LAST10:
            score += 2
            breakdown['xg_slope'] = 2
        else:
            breakdown['xg_slope'] = 0
        
        # 4.2 Turnover rate decrease (+1 point)
        if self.check_turnovers_decreasing(stats):
            score += 1
            breakdown['turnovers_down'] = 1
        else:
            breakdown['turnovers_down'] = 0
        
        # 4.3 Attack conversion rate decrease (+1 point)
        if self.check_attack_conversion_down(stats):
            score += 1
            breakdown['attack_conversion_down'] = 1
        else:
            breakdown['attack_conversion_down'] = 0
        
        # 4.4 Fouls down AND pass speed down (+1 point)
        if self.check_fouls_and_pass_speed_down(stats, events):
            score += 1
            breakdown['fouls_pass_down'] = 1
        else:
            breakdown['fouls_pass_down'] = 0
        
        # ============ [NEW S5] PSYCHOLOGICAL GAME STATE (Max 3 points) ============
        
        # 5.1 Lead kill-mode: Leading team slowing tempo (+2 points)
        if self.check_lead_kill_mode(stats, goals_data):
            score += 2
            breakdown['lead_kill_mode'] = 2
        else:
            breakdown['lead_kill_mode'] = 0
        
        # 5.2 Draw-mode: Both teams accepting draw (+1 point)
        if self.check_draw_mode(stats, goals_data):
            score += 1
            breakdown['draw_mode'] = 1
        else:
            breakdown['draw_mode'] = 0
        
        # ============ SUPPORTING RULES (Bonuses) ============
        
        # False pressure signal
        if self.check_false_pressure(events, minute):
            score += 1
            breakdown['false_pressure'] = 1
        else:
            breakdown['false_pressure'] = 0
        
        # Compact defense/balance
        if self.check_compact_defense(stats, poss_diff):
            score += 1
            breakdown['compact_defense'] = 1
        else:
            breakdown['compact_defense'] = 0
        
        # Shot quality collapse
        if self.check_shot_quality_collapse(stats):
            score += 1
            breakdown['shot_quality_collapse'] = 1
        else:
            breakdown['shot_quality_collapse'] = 0
        
        # ============ PENALTY-BASED FILTERS ============
        
        # Red card with pressure increase
        if self.check_red_card_with_pressure(events, minute):
            penalties += config.PENALTY_RED_CARD_WITH_PRESSURE
            breakdown['penalty_red_card'] = config.PENALTY_RED_CARD_WITH_PRESSURE
        
        # xG difference > 1.3
        home_xg, away_xg = team_xg_split
        xg_diff = abs(home_xg - away_xg)
        if xg_diff > config.MAX_XG_DIFFERENCE:
            penalties += config.PENALTY_XG_DIFF
            breakdown['penalty_xg_diff'] = config.PENALTY_XG_DIFF
        
        # 2nd half penalty
        if self.check_second_half_penalty(events):
            penalties += config.PENALTY_SECOND_HALF_PENALTY
            breakdown['penalty_2h_penalty'] = config.PENALTY_SECOND_HALF_PENALTY
        
        # xG slope rising (tempo accelerating)
        if xg_slope_last10 > 0.10:
            penalties += config.PENALTY_XG_SLOPE_RISING
            breakdown['penalty_xg_slope_rising'] = config.PENALTY_XG_SLOPE_RISING
    
        # ============ BONUS TAG ============
        total_goals = goals_data.get('home', 0) + goals_data.get('away', 0)
        if total_goals >= config.BONUS_FIRST_HALF_MIN_GOALS and second_half_xg <= config.BONUS_SECOND_HALF_MAX_XG:
            bonus_tag = "🔥 Early goals, dead tempo"
        
        # Final score with penalties
        final_score = max(0, score + penalties)  # Penalties are negative
        breakdown['raw_score'] = score
        breakdown['penalties'] = penalties
        breakdown['final_score'] = final_score
        
        return final_score, breakdown, bonus_tag

    def calculate_stability_index(
        self,
        match_score: int,
        effective_threshold: float,
        risk_index: float,
        tempo_metrics: Dict,
    ) -> Tuple[float, float]:
        """Combine score cushion, risk, and tempo pressure into a stability index."""
        margin = match_score - effective_threshold
        normalized_margin = max(0.0, min(1.0, margin / max(1.0, config.STABILITY_MARGIN_NORMALIZER)))

        tempo_index = max(0.0, tempo_metrics.get('tempo_index', 0.0))
        card_pressure = tempo_metrics.get('cards_recent', 0) / max(1, config.RISK_CARD_EVENTS_CAP)

        raw_index = (
            0.45
            + normalized_margin
            - risk_index * config.STABILITY_RISK_WEIGHT
            - tempo_index * config.STABILITY_TEMPO_WEIGHT
            - card_pressure * config.STABILITY_CARD_WEIGHT
        )

        stability_index = max(0.0, min(1.0, round(raw_index, 3)))
        return stability_index, round(margin, 2)
    
    # ============ NEW HELPER METHODS FOR S4 & S5 ============
    
    def calculate_xg_slope(self, events: List[Dict], current_minute: int) -> float:
        """Calculate xG slope over last 10 minutes (positive = increasing tempo)"""
        if not events or current_minute < 10:
            return 0.0
        
        # Get events in last 10 minutes
        recent_events = [e for e in events if e.get('time', {}).get('elapsed', 0) >= current_minute - 10]
        
        if len(recent_events) < 2:
            return 0.0
        
        # Count dangerous actions (shots, key passes)
        dangerous_actions = [e for e in recent_events if e.get('type') in ['Goal', 'Shot', 'Var']]
        
        # Simple slope: more actions in recent 5min vs previous 5min
        mid_point = current_minute - 5
        recent_5 = len([e for e in dangerous_actions if e.get('time', {}).get('elapsed', 0) >= mid_point])
        prev_5 = len([e for e in dangerous_actions if e.get('time', {}).get('elapsed', 0) < mid_point])
        
        # Normalize to slope
        slope = (recent_5 - prev_5) * 0.1  # Scale factor
        return slope
    
    def check_turnovers_decreasing(self, stats: List[Dict]) -> bool:
        """Check if turnover rate is decreasing (approximated by passes completed)"""
        # High pass accuracy = low turnovers
        home_pass_acc = self.extract_statistic(stats, 'Passes %', 0) or 70
        away_pass_acc = self.extract_statistic(stats, 'Passes %', 1) or 70
        avg_pass_acc = (home_pass_acc + away_pass_acc) / 2
        
        # If average pass accuracy > 75%, turnovers are low
        return avg_pass_acc > 75
    
    def check_attack_conversion_down(self, stats: List[Dict]) -> bool:
        """Check if attack conversion rate is decreasing"""
        total_shots = self.extract_statistic(stats, 'Total Shots') or 0
        shots_on_target = self.extract_statistic(stats, 'Shots on Goal') or 0
        
        if total_shots == 0:
            return True
        
        conversion = shots_on_target / total_shots
        # Low conversion (<30%) indicates poor attacking efficiency
        return conversion < 0.30
    
    def check_fouls_and_pass_speed_down(self, stats: List[Dict], events: List[Dict]) -> bool:
        """Check if fouls decreasing AND pass speed slowing"""
        total_fouls = self.extract_statistic(stats, 'Fouls') or 0
        total_passes = self.extract_statistic(stats, 'Total passes') or 1
        
        # Low fouls (<15) and high pass count (>400) = slow tempo
        return total_fouls < 15 and total_passes > 400
    
    def check_lead_kill_mode(self, stats: List[Dict], goals_data: Dict) -> bool:
        """Check if leading team is killing tempo (lateral/back passes)"""
        home_goals = goals_data.get('home', 0)
        away_goals = goals_data.get('away', 0)
        
        # Only applies when one team is leading
        if home_goals == away_goals:
            return False
        
        leading_team_idx = 0 if home_goals > away_goals else 1
        
        # Check possession and pass accuracy (high = time-wasting)
        possession = self.extract_statistic(stats, 'Ball Possession', leading_team_idx) or 50
        pass_acc = self.extract_statistic(stats, 'Passes %', leading_team_idx) or 70
        
        # Leading team with high possession (>55%) and high pass accuracy (>80%) = kill mode
        return possession > 55 and pass_acc > 80
    
    def check_draw_mode(self, stats: List[Dict], goals_data: Dict) -> bool:
        """Check if both teams accepting draw (low pressure)"""
        home_goals = goals_data.get('home', 0)
        away_goals = goals_data.get('away', 0)
        
        # Only applies to draws
        if home_goals != away_goals:
            return False
        
        total_shots = self.extract_statistic(stats, 'Total Shots') or 0
        
        # Very low shots (<10) in a draw = both teams passive
        return total_shots < 10
    
    def check_false_pressure(self, events: List[Dict], current_minute: int) -> bool:
        """Detect false pressure: corners but low quality shots"""
        if not events or current_minute < 10:
            return False
        
        recent_events = [e for e in events if e.get('time', {}).get('elapsed', 0) >= current_minute - 10]
        
        corners = len([e for e in recent_events if e.get('detail') == 'Corner'])
        shots_on_target = len([e for e in recent_events if e.get('detail') in ['Normal Goal', 'Shot on target']])
        total_shots = len([e for e in recent_events if 'Shot' in str(e.get('type', ''))])
        
        # ≥2 corners but ≤1 on target and low xG/shot
        if corners >= config.FALSE_PRESSURE_CORNERS_LAST10 and shots_on_target <= config.FALSE_PRESSURE_ON_TARGET:
            if total_shots > 0:
                # Approximate xG per shot
                xg_per_shot = (shots_on_target * 0.35) / max(total_shots, 1)
                return xg_per_shot <= config.FALSE_PRESSURE_XG_PER_SHOT
        
        return False
    
    def check_compact_defense(self, stats: List[Dict], poss_diff: float) -> bool:
        """Check for compact defense/balance"""
        if poss_diff > config.COMPACT_DEFENSE_POSS_DIFF:
            return False
        
        # Low possession variance = balanced game
        # (Simplified: just check if possession diff is low)
        return True
    
    def check_shot_quality_collapse(self, stats: List[Dict]) -> bool:
        """Check if shot quality is collapsing (distance up, blocked ratio up)"""
        total_shots = self.extract_statistic(stats, 'Total Shots') or 0
        blocked_shots = self.extract_statistic(stats, 'Blocked Shots') or 0
        
        if total_shots == 0:
            return False
        
        blocked_ratio = blocked_shots / total_shots
        
        # High blocked ratio (≥45%) = poor shot quality
        return blocked_ratio >= config.SHOT_QUALITY_BLOCKED_RATIO
    
    def check_red_card_with_pressure(self, events: List[Dict], current_minute: int) -> bool:
        """Check if red card occurred AND pressure increased after"""
        red_cards = [e for e in events if e.get('detail') == 'Red Card']
        
        if not red_cards:
            return False
        
        # Get last red card minute
        last_red_minute = red_cards[-1].get('time', {}).get('elapsed', 0)
        
        # Check if there were shots/actions after red card
        actions_after_red = [e for e in events 
                            if e.get('time', {}).get('elapsed', 0) > last_red_minute 
                            and e.get('type') in ['Shot', 'Goal']]
        
        # If 3+ actions after red, pressure increased
        return len(actions_after_red) >= 3
    
    def check_second_half_penalty(self, events: List[Dict]) -> bool:
        """Check if penalty occurred in 2nd half"""
        penalties_2h = [e for e in events 
                       if 'Penalty' in str(e.get('detail', '')) 
                       and e.get('time', {}).get('elapsed', 0) >= 45]
        
        return len(penalties_2h) > 0
    
    def analyze_team_form(self, team_id: int) -> float:
        recent_matches = self.api_client.get_team_form(team_id, last=5)
        
        if not recent_matches:
            return 1.0
        
        total_goals = 0
        match_count = len(recent_matches)
        
        if match_count == 0:
            return 1.0
        
        for match in recent_matches:
            goals = match.get('goals')
            teams = match.get('teams')
            
            # Skip if goals data is None or invalid
            if not goals or not isinstance(goals, dict):
                continue
            
            if not teams or not isinstance(teams, dict):
                continue
            
            # Determine if home or away and safely get goal count
            if teams.get('home', {}).get('id') == team_id:
                home_goals = goals.get('home')
                if home_goals is not None:
                    total_goals += home_goals
            else:
                away_goals = goals.get('away')
                if away_goals is not None:
                    total_goals += away_goals
        
        # Recalculate match count based on valid data
        if total_goals == 0:
            return 1.0
        
        avg_goals = total_goals / max(1, match_count)
        return round(avg_goals, 2)
    
    def analyze_h2h_history(self, team1_id: int, team2_id: int) -> float:
        """Analyze head-to-head history"""
        h2h_matches = self.api_client.get_h2h_matches(team1_id, team2_id, last=5)
        
        if not h2h_matches:
            return 2.5
        
        total_goals = 0
        valid_matches = 0
        
        for match in h2h_matches:
            goals = match.get('goals')
            
            # Skip if goals data is None or invalid
            if not goals or not isinstance(goals, dict):
                continue
            
            home_goals = goals.get('home')
            away_goals = goals.get('away')
            
            if home_goals is not None and away_goals is not None:
                total_goals += home_goals + away_goals
                valid_matches += 1
        
        if valid_matches == 0:
            return 2.5
        
        avg_goals = total_goals / valid_matches
        return round(avg_goals, 2)
    
    def check_cache(self, fixture_id: int, score: str, minute: int, last_event_time: int) -> Optional[float]:
        """Check if match already analyzed with same state (returns cached confidence if delta < 0.06)"""
        cache_key = f"{fixture_id}"
        
        if cache_key not in self.analysis_cache:
            return None
        
        cached = self.analysis_cache[cache_key]
        
        # Check if state is identical
        if (cached['score'] == score and 
            cached['minute'] == minute and 
            cached.get('last_event_time') == last_event_time):
            return cached['confidence']  # Exact match, skip
        
        # State changed, check if confidence delta is significant
        return None  # Allow re-analysis
    
    def update_cache(self, fixture_id: int, score: str, minute: int, last_event_time: int, confidence: float):
        """Update analysis cache"""
        cache_key = f"{fixture_id}"
        self.analysis_cache[cache_key] = {
            'score': score,
            'minute': minute,
            'last_event_time': last_event_time,
            'confidence': confidence
        }
    
    def classify_confidence(self, confidence: float) -> str:
        """Classify match based on confidence score"""
        if confidence >= config.STRONG_CONFIDENCE:
            return "strong_candidate"
        elif confidence >= config.CANDIDATE_CONFIDENCE:
            return "candidate"
        elif confidence >= config.WEAK_CONFIDENCE:
            return "weak_candidate"
        else:
            return "reject"
    
    def check_elimination_filters(self, events: List[Dict], combined_xg: float, 
                                  home_xg: float, away_xg: float) -> Tuple[bool, str]:
        """Check OLD elimination filters (DEPRECATED - now using penalty system)"""
        return False, ""  # No hard elimination anymore
    
    def analyze_match(self, fixture: Dict) -> Optional[Dict]:
        """
        Comprehensive match analysis with 30-point scoring system (S1-S5)
        
        Returns:
            Analysis result dictionary or None if doesn't qualify
        """
        fixture_id = fixture.get('fixture', {}).get('id')
        minute = fixture.get('fixture', {}).get('status', {}).get('elapsed', 0)
        teams = fixture.get('teams', {})
        goals = fixture.get('goals', {})
        league = fixture.get('league', {})
        
        # Extract team info
        home_team = teams.get('home', {})
        away_team = teams.get('away', {})
        home_id = home_team.get('id')
        away_id = away_team.get('id')
        
        if not home_id or not away_id:
            self.logger.debug(f"Invalid team IDs for match {fixture_id}")
            return None
        
        # Score filter: Check if score pattern is allowed
        home_goals = goals.get('home') or 0
        away_goals = goals.get('away') or 0
        score_tuple = (home_goals, away_goals)
        
        if score_tuple in config.EXCLUDED_SCORES:
            self.logger.debug(f"Match {fixture_id} excluded: high volatility score {score_tuple}")
            return None
        
        if score_tuple not in config.ALLOWED_SCORES and score_tuple not in [(h, a) for a, h in config.ALLOWED_SCORES]:
            self.logger.debug(f"Match {fixture_id} excluded: score not in allowed patterns")
            return None
        
        # Get detailed statistics
        stats = self.api_client.get_match_statistics(fixture_id)
        events = self.api_client.get_match_events(fixture_id)
        
        if not stats:
            self.logger.debug(f"No statistics available for match {fixture_id}")
            return None
        
        # Get last event time for cache key
        last_event_time = max([e.get('time', {}).get('elapsed', 0) for e in events], default=0) if events else 0
        
        # Check cache
        score_str = f"{home_goals}-{away_goals}"
        cached_confidence = self.check_cache(fixture_id, score_str, minute, last_event_time)
        if cached_confidence is not None:
            self.logger.debug(f"Match {fixture_id} cached (no significant change)")
            return None  # Skip, already analyzed with same state
        
        # Calculate xG for both teams
        combined_xg, second_half_xg, team_xg_split = self.calculate_xg_from_stats(stats)

        # Calculate match score (30-point system)
        match_score, score_breakdown, bonus_tag = self.calculate_match_score(
            stats,
            events,
            goals,
            minute,
            combined_xg,
            second_half_xg,
            team_xg_split,
        )

        # Tempo & risk evaluation (ensures lower threshold without losing control)
        tempo_metrics = self.calculate_tempo_metrics(events or [], minute)
        risk_index = self.calculate_risk_index(tempo_metrics)
        score_breakdown['risk_index'] = risk_index
        score_breakdown['risk_penalty'] = 0

        if risk_index > config.MAX_RISK_INDEX:
            self.logger.debug(
                f"Match {fixture_id} rejected: risk index too high ({risk_index})"
            )
            return None

        if risk_index > config.RISK_WARNING_THRESHOLD:
            match_score = max(0, match_score - 1)
            score_breakdown['risk_penalty'] = -1

        # S3: Team Form & Historical Data (Max 2 points)
        home_npxg = self.analyze_team_form(home_id)
        away_npxg = self.analyze_team_form(away_id)

        if home_npxg <= config.MAX_TEAM_NPXG and away_npxg <= config.MAX_TEAM_NPXG:
            match_score += 1
            score_breakdown['team_form'] = 1
        else:
            score_breakdown['team_form'] = 0
        
        h2h_avg = self.analyze_h2h_history(home_id, away_id)
        if h2h_avg <= config.MAX_H2H_AVG_GOALS:
            match_score += 1
            score_breakdown['h2h'] = 1
        else:
            score_breakdown['h2h'] = 0
        
        # Apply temporal adjustment (minute-based tolerance)
        effective_threshold = config.REQUIRED_SCORE
        threshold_adjustments: Dict[str, int] = {}

        if minute >= 80 and config.TOLERANCE_MINUTE_80:
            adjustment = config.TOLERANCE_MINUTE_80
            effective_threshold -= adjustment
            threshold_adjustments['minute_80'] = -adjustment
        elif minute >= 70 and config.TOLERANCE_MINUTE_70:
            adjustment = config.TOLERANCE_MINUTE_70
            effective_threshold -= adjustment
            threshold_adjustments['minute_70'] = -adjustment

        if minute >= config.LATE_WINDOW_THRESHOLD_MINUTE:
            adjustment = config.LATE_WINDOW_THRESHOLD_REDUCTION
            if adjustment:
                effective_threshold -= adjustment
                threshold_adjustments['late_window'] = -adjustment

        if risk_index <= config.LOW_RISK_RELAXATION_THRESHOLD:
            adjustment = config.LOW_RISK_RELAXATION_DELTA
            if adjustment:
                effective_threshold -= adjustment
                threshold_adjustments['low_risk'] = -adjustment

        effective_threshold = max(config.MINIMUM_EFFECTIVE_THRESHOLD, effective_threshold)
        score_breakdown['threshold_base'] = config.REQUIRED_SCORE
        score_breakdown['threshold_adjustments'] = threshold_adjustments
        score_breakdown['effective_threshold'] = effective_threshold

        # Check if match qualifies
        if match_score < effective_threshold:
            self.logger.debug(f"Match {fixture_id} failed score check: {match_score}/{config.MAX_TOTAL_SCORE} (threshold: {effective_threshold})")
            return None

        stability_index, stability_margin = self.calculate_stability_index(
            match_score,
            effective_threshold,
            risk_index,
            tempo_metrics,
        )
        score_breakdown['stability_index'] = stability_index
        score_breakdown['stability_margin'] = stability_margin

        if (
            stability_index < config.MIN_STABILITY_INDEX
            and stability_margin < config.STABILITY_MARGIN_RECOVERY
        ):
            self.logger.debug(
                f"Match {fixture_id} rejected: unstable window (stability={stability_index:.2f}, margin={stability_margin:.2f})"
            )
            return None

        # Calculate confidence and classify
        confidence = match_score / config.MAX_TOTAL_SCORE
        classification = self.classify_confidence(confidence)

        if risk_index > config.RISK_WARNING_THRESHOLD and classification == "strong_candidate":
            classification = "candidate"
        elif risk_index > config.RISK_WARNING_THRESHOLD and classification == "candidate":
            classification = "weak_candidate"

        if classification == "strong_candidate" and stability_margin < config.STABILITY_STRONG_MARGIN:
            classification = "candidate"
        if classification == "candidate" and stability_index < (config.MIN_STABILITY_INDEX + 0.1):
            classification = "weak_candidate"

        if classification == "weak_candidate" and stability_index < config.MIN_STABILITY_INDEX:
            self.logger.debug(
                f"Match {fixture_id} rejected: weak candidate with low stability ({stability_index:.2f})"
            )
            return None

        if classification == "reject":
            self.logger.debug(f"Match {fixture_id} rejected: confidence too low ({confidence:.2f})")
            return None

        # Update cache
        self.update_cache(fixture_id, score_str, minute, last_event_time, confidence)
        
        # Build reasons list
        reasons = []
        if score_breakdown.get('xg_slope', 0) > 0:
            reasons.append("tempo collapse")
        if score_breakdown.get('lead_kill_mode', 0) > 0:
            reasons.append("kill-mode")
        if score_breakdown.get('false_pressure', 0) > 0:
            reasons.append("false pressure")
        if score_breakdown.get('draw_mode', 0) > 0:
            reasons.append("draw acceptance")
        if bonus_tag:
            reasons.append("early goals dead tempo")
        if risk_index <= 0.35:
            reasons.append("tempo stabilized")
        elif risk_index > config.RISK_WARNING_THRESHOLD:
            reasons.append("tempo caution")
        if stability_margin >= config.STABILITY_STRONG_MARGIN:
            reasons.append("stability cushion")
        elif stability_index < (config.MIN_STABILITY_INDEX + 0.1):
            reasons.append("monitor pressure")

        if 'late_window' in threshold_adjustments:
            reasons.append("late window tolerance")
        if 'low_risk' in threshold_adjustments:
            reasons.append("low-risk cushion")

        # Extract detailed stats
        total_shots = self.extract_statistic(stats, 'Total Shots') or 0
        shots_on_target = self.extract_statistic(stats, 'Shots on Goal') or 0
        total_corners = self.extract_statistic(stats, 'Corner Kicks') or 0
        home_poss = self.extract_statistic(stats, 'Ball Possession', 0) or 50
        away_poss = self.extract_statistic(stats, 'Ball Possession', 1) or 50
        # Dynamic event stats for reporting
        second_half_shots_count = self.count_events_in_range(events or [], 45, minute, self.is_shot_event)
        if second_half_shots_count == 0 and not events:
            second_half_shots_count = int(total_shots * 0.45)

        second_half_sot_count = self.count_events_in_range(events or [], 45, minute, self.is_shot_on_target_event)
        if second_half_sot_count == 0 and not events:
            second_half_sot_count = int(shots_on_target * 0.5)

        last_15min_shots_count = self.count_events_in_range(events or [], minute - 15, minute, self.is_shot_event)
        if last_15min_shots_count == 0 and not events:
            last_15min_shots_count = int(total_shots * 0.2)

        shots_last10 = self.count_events_in_range(events or [], minute - 10, minute, self.is_shot_event)
        on_target_last10 = self.count_events_in_range(events or [], minute - 10, minute, self.is_shot_on_target_event)
        corners_last10 = self.count_events_in_range(
            events or [],
            minute - 10,
            minute,
            lambda e: str(e.get('detail', '')).lower() == 'corner',
        )

        if not events:
            shots_last10 = int(total_shots * 0.15)
            on_target_last10 = int(shots_on_target * 0.2)
            corners_last10 = int(total_corners * 0.2)

        return {
            'fixture_id': fixture_id,
            'home_team': home_team.get('name', 'Unknown'),
            'away_team': away_team.get('name', 'Unknown'),
            'minute': minute,
            'score': f"{goals.get('home') or 0}-{goals.get('away') or 0}",
            'league': league.get('name', 'Unknown'),
            'league_country': league.get('country', 'N/A'),
            'total_xg': combined_xg,
            'second_half_xg': second_half_xg,
            'home_xg': team_xg_split[0],
            'away_xg': team_xg_split[1],
            'total_shots': total_shots,
            'shots_on_target': shots_on_target,
            'second_half_shots': second_half_shots_count,
            'last_15min_shots': last_15min_shots_count,
            'total_corners': total_corners,
            'possession_diff': abs(home_poss - away_poss),
            'home_form_npxg': home_npxg,
            'away_form_npxg': away_npxg,
            'h2h_avg_goals': h2h_avg,
            'match_score': match_score,
            'max_score': config.MAX_TOTAL_SCORE,
            'confidence': round(confidence, 2),
            'classification': classification,
            'reasons': reasons,
            'risk_index': risk_index,
            'stability_index': stability_index,
              'stability_margin': stability_margin,
              'tempo_metrics': tempo_metrics,
              'score_breakdown': score_breakdown,
              'thresholds': {
                  'base': config.REQUIRED_SCORE,
                  'effective': effective_threshold,
                  'adjustments': threshold_adjustments,
              },
              'stats': {
                  'xg_total': combined_xg,
                'xg_last10': round(abs(tempo_metrics['xg_slope']), 2),
                'shots_last10': shots_last10,
                'on_target_last10': on_target_last10,
                'corners_last10': corners_last10,
                'possession_diff': abs(home_poss - away_poss),
                'risk_index': risk_index,
                'tempo_index': tempo_metrics['tempo_index'],
                'dangerous_actions_last10': tempo_metrics['dangerous_actions'],
                'pressure_events_last10': tempo_metrics['pressure_events'],
                'cards_last10': tempo_metrics['cards_recent'],
            },
            'tags': [bonus_tag] if bonus_tag else [],
        }
