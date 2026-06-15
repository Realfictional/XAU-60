import os
import sys
from smartmoneyconcepts.smc import smc

if os.getenv('SMC_CREDIT', '1') == '1':
    try:
        print("Thank you for using SmartMoneyConcepts! Please show your support: https://github.com/joshyattridge/smart-money-concepts")
    except Exception:
        pass