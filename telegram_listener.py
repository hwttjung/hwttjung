# Legacy Facade & Cron Entrypoint for telegram_listener
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from daemons.telegram_listener import *

if __name__ == "__main__":
    from daemons.telegram_listener import main
    main()
