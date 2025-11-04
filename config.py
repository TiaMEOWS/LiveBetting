"""
Configuration settings for 24/7 Live Betting Analysis System
"""

# API-Football Configuration (Direct API, not RapidAPI)
API_FOOTBALL_KEY = "ec8cab076be728fc60b6bcf02364061f"
API_FOOTBALL_HOST = "v3.football.api-sports.io"
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"

# Telegram Configuration
TELEGRAM_BOT_TOKEN = "8081161139:AAGeFivr72frVbX2ZD9qsueruMg6XTA_DbQ"
TELEGRAM_CHAT_ID = "5593711257"

# API Usage Limits
DAILY_REQUEST_LIMIT = 7500
HOURLY_REQUEST_BUDGET = 312  # 7500/24
EMERGENCY_BUFFER = 500
MAX_REQUESTS_PER_SCAN = 20

# Scanning Configuration
BASE_SCAN_INTERVAL = 60  # 1 minute (seconds)
OFF_PEAK_INTERVAL = 60  # 1 minute for low activity
PEAK_HOURS_START = 8  # 08:00 UTC
PEAK_HOURS_END = 1  # 01:00 UTC (next day)

# Match Analysis Window
MIN_MINUTE = 60
MAX_MINUTE = 72
MIN_MINUTE_EXTENDED = 58  # Extended range when low traffic
MAX_MINUTE_EXTENDED = 75

# Analysis Thresholds - UPGRADED 30-POINT SCORING SYSTEM
# Total Score Required: ≥12 out of 30 points (relaxed for higher recall)
REQUIRED_SCORE = 12  # Minimum score to trigger alert
MAX_TOTAL_SCORE = 30  # Maximum possible score

# Confidence Thresholds
STRONG_CONFIDENCE = 0.70  # ≥70% = strong_candidate
CANDIDATE_CONFIDENCE = 0.55  # ≥55% = candidate
WEAK_CONFIDENCE = 0.45  # ≥45% = weak_candidate

# Score Filters (relaxed)
ALLOWED_SCORES = [(0,0), (1,0), (0,1), (1,1), (2,0), (0,2), (2,1), (1,2)]  # Included score patterns
EXCLUDED_SCORES = [(2,2), (3,2), (2,3), (3,3)]  # High volatility scores

# Match-Wide Criteria (Max 9 points)
MAX_COMBINED_XG = 2.2  # ≤2.2 = +3 points
MAX_TOTAL_SHOTS = 14  # ≤14 = +2 points
MAX_SHOTS_ON_TARGET = 5  # ≤5 = +2 points
MAX_CORNERS = 7  # ≤7 = +1 point
MAX_POSSESSION_DIFF = 18  # ≤18% = +1 point

# Second Half Criteria (Max 11 points)
MAX_SECOND_HALF_XG = 0.6  # ≤0.6 = +3 points
MAX_SECOND_HALF_SHOTS = 5  # ≤5 = +2 points
MAX_SECOND_HALF_SHOTS_ON_TARGET = 2  # ≤2 = +2 points
MAX_LAST_15MIN_SHOTS = 3  # ≤3 = +2 points
MAX_SECOND_HALF_CORNERS = 3  # ≤3 = +1 point
MAX_SECOND_HALF_POSSESSION_DIFF = 15  # ≤15% = +1 point

# Team Form & Historical Data (Max 2 points)
MAX_TEAM_NPXG = 1.3  # Last 5 matches ≤1.3 = +1 point
MAX_H2H_AVG_GOALS = 2.1  # ≤2.1 = +1 point

# Penalty-Based Filters (no hard elimination, just penalties)
PENALTY_RED_CARD_WITH_PRESSURE = -3  # Red card + tempo increase
PENALTY_XG_DIFF = -2  # xG diff > 1.3
PENALTY_SECOND_HALF_PENALTY = -4  # Penalty in 2nd half
PENALTY_XG_SLOPE_RISING = -3  # xG slope > 0.10 (tempo accelerating)

MAX_XG_DIFFERENCE = 1.3  # More tolerant (was 1.0)

# Bonus Detection
BONUS_FIRST_HALF_MIN_GOALS = 2  # First half ≥2 goals
BONUS_SECOND_HALF_MAX_XG = 0.5  # AND second half xG ≤0.5

# [NEW S4] Momentum & Tempo Dynamics Thresholds (max 5 points)
MAX_XG_SLOPE_LAST10 = 0  # xG slope ≤ 0 (no increase) → +2
TURNOVERS_DOWN_THRESHOLD = 0.15  # Turnover rate decrease → +1
ATTACK_CONVERSION_DOWN_THRESHOLD = 0.20  # Attack conversion decrease → +1
FOULS_AND_PASS_SPEED_DOWN = True  # Fouls↓ AND pass speed↓ → +1

# [NEW S5] Psychological Game State Thresholds (max 3 points)
LEAD_KILL_MODE_THRESHOLD = 0.60  # Lateral/back pass ratio ≥60% when leading → +2
DRAW_MODE_THRESHOLD = 0.30  # Both teams low pressure (<30%) → +1

# Supporting Rules Bonuses
FALSE_PRESSURE_CORNERS_LAST10 = 2  # ≥2 corners
FALSE_PRESSURE_XG_PER_SHOT = 0.08  # ≤0.08 xG/shot
FALSE_PRESSURE_ON_TARGET = 1  # ≤1 on target
COMPACT_DEFENSE_POSS_DIFF = 15  # ≤15%
COMPACT_DEFENSE_POSS_VAR = 7  # ≤7
SHOT_QUALITY_DISTANCE_INCREASE = 1.2  # Avg shot distance multiplier
SHOT_QUALITY_BLOCKED_RATIO = 0.45  # ≥45% blocked

# Temporal Adjustment (minute-based tolerance)
TOLERANCE_MINUTE_70 = 1  # Reduce threshold by 1 point if minute ≥ 70
TOLERANCE_MINUTE_80 = 2  # Reduce threshold by 2 points if minute ≥ 80

# Cache Strategy (avoid duplicate analysis)
CACHE_DELTA_CONFIDENCE = 0.06  # Re-alert only if Δconfidence ≥ 0.06

# Match Tracking
MATCH_MEMORY_HOURS = 24
DATABASE_FILE = "match_tracking.json"
LOG_FILE = "betting_system.log"

# Priority Leagues (for focused analysis during high load)
PRIORITY_LEAGUES = [
    39,   # Premier League
    140,  # La Liga
    78,   # Bundesliga
    135,  # Serie A
    61,   # Ligue 1
    2,    # Champions League
    3,    # Europa League
]

# Retry Configuration
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2  # Exponential: 2, 4, 8 seconds
REQUEST_TIMEOUT = 10  # seconds

# Telegram Control Settings
TELEGRAM_POLLING = True
TELEGRAM_POLL_INTERVAL = 1
SHOW_PAUSE_BUTTONS = True
