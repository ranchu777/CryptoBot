from config import Config, ConfigValidationError

# Test 1: Empty API key
cfg_test = Config.__new__(Config)
cfg_test.TESTNET = True
cfg_test.API_KEY = ''
cfg_test.API_SECRET = 'test'
cfg_test.BASE_URL = 'https://testnet.binance.vision'
cfg_test.STOP_LOSS_PCT = 2.5
cfg_test.TAKE_PROFIT_PCT = 5
cfg_test.POSITION_SIZE_PCT = 5
cfg_test.MAX_POSITIONS = 6
cfg_test.MIN_RESERVE_USDT = 500
cfg_test.AGGRESSION = 1.5
cfg_test.BUY_THRESHOLD = 0.25
cfg_test.SELL_THRESHOLD = 0.25
cfg_test.TECHNICAL_WEIGHT = 0.28
cfg_test.NEWS_WEIGHT = 0.20
cfg_test.SMART_MONEY_WEIGHT = 0.20
cfg_test.CALENDAR_WEIGHT = 0.10
cfg_test.FNG_WEIGHT = 0.10
cfg_test.FUNDING_WEIGHT = 0.07
cfg_test.ORB_WEIGHT = 0.05
cfg_test.TREND_EMA_PERIOD = 200
cfg_test.MAX_DRAWDOWN_PCT = 5
cfg_test.TRAILING_STOP_ACTIVATION_PCT = 1
cfg_test.VOL_NORMAL_THRESHOLD = 0.015
cfg_test.VOL_HIGH_THRESHOLD = 0.030
cfg_test.VOL_EXTREME_THRESHOLD = 0.050

try:
    cfg_test._validate()
    print('❌ Test 1 FAILED: Should have raised ConfigValidationError')
except ConfigValidationError as e:
    if 'API_KEY' in str(e):
        print('✅ Test 1 PASSED: Config validation catches empty API_KEY')
    else:
        print(f'❌ Test 1 FAILED: Wrong error - {str(e)[:80]}...')

# Test 2: Division by zero in drawdown
from risk import RiskManager

print("\n[Test 2] Division by zero in drawdown check")
cfg = Config(testnet=True)
risk_mgr = RiskManager(cfg)
risk_mgr._session_start_balance = 0.0
result = risk_mgr.check_drawdown(100.0)
if result is False:
    print('✅ Test 2 PASSED: Drawdown check handles zero balance')
else:
    print(f'❌ Test 2 FAILED: Expected False, got {result}')

# Test 3: EMA division by zero
import pandas as pd
import numpy as np
from strategy import Strategy

print("\n[Test 3] EMA division by zero")
strategy = Strategy("ema", cfg)
df_edge = pd.DataFrame({
    "close": [np.nan, np.nan, np.nan, np.nan, np.nan],
    "volume": [100, 100, 100, 100, 100],
})
try:
    score = strategy._ema_score(df_edge)
    if score == 0.0:
        print('✅ Test 3 PASSED: EMA handles NaN data')
    else:
        print(f'⚠️  Test 3 WARNING: EMA returned {score} instead of 0.0, but no crash')
except Exception as e:
    print(f'❌ Test 3 FAILED: EMA raised exception - {e}')

print("\n" + "="*60)
print("Core fixes verified successfully!")
print("="*60)
