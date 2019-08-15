import platform
import types
import os

config = types.SimpleNamespace()

if platform.system().lower() == 'windows':
    config.tdx_root = 'C:\\tdx\\tdx_7.46'
else:
    config.tdx_root = '~/stocks/tdx/'

config.concurrency = os.cpu_count()
config.sub_group_count = 2