""" This module implements methods interacting with Chrome DevTools """
import subprocess
import tempfile

from blaze.config import Config
from blaze.logger import logger

from .config import get_chrome_command, get_chrome_flags
from .har import har_from_json, Har

REMOTE_DEBUGGING_PORT = 9301

def capture_har(url: str, config: Config) -> Har:
  """
  capture_har spawns a headless chrome instance and connects to its remote debugger
  in order to extract the HAR file generated by loading the given URL.
  """
  log = logger.with_namespace('capture_har')
  with tempfile.TemporaryDirectory(prefix='blaze_har_capture', dir='/tmp') as tmp_dir:
    # configure chrome
    rdp_flag = '--remote-debugging-port={}'.format(REMOTE_DEBUGGING_PORT)
    chrome_flags = get_chrome_flags(tmp_dir, extra_flags=[rdp_flag])
    chrome_cmd = get_chrome_command('', chrome_flags, config)

    # spawn the chrome process
    log.debug('spawning chrome', rdp_port=REMOTE_DEBUGGING_PORT, user_data_dir=tmp_dir)
    chrome_proc = subprocess.Popen(chrome_cmd, encoding='utf-8')

    # configure the HAR capturer
    har_capture_cmd = [
      config.chrome_har_capturer_bin,
      '-h', 'localhost',
      '-p', str(REMOTE_DEBUGGING_PORT),
      '-i',
      url
    ]

    # spawn the HAR capturer process
    try:
      log.debug('spawning har capturer', url=url)
      har_capture_proc = subprocess.run(har_capture_cmd, stdout=subprocess.PIPE)
      har_capture_proc.check_returncode()
    finally:
      log.debug('terminating chrome process')
      chrome_proc.terminate()
    return har_from_json(har_capture_proc.stdout)
