import logging  # migrated from print()
import subprocess
import sys

logging.getLogger(__name__).info('Installing requirements...')
subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)

logging.getLogger(__name__).info('Installing Playwright browsers...')
subprocess.run([sys.executable, "-m", "playwright", "install"], check=True)

logging.getLogger(__name__).info("\\n[OK] Setup complete! Run 'python main.py' to start MARK XXV.")

