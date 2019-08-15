from datetime import datetime
from libs.tradingday import TradingDay

import os


now = datetime.now()
if now.replace(hour=15, minute=0) < now < now.replace(hour=15, minute=10):
    os.system("shutdown -t 90 -s -f")

if __name__=="__main__":
    now = datetime.now()
    # now = datetime.now().replace(hour=9, minute=0)
    f = os.path.join(os.getcwd(), 'hdf5', now.strftime('%Y%m%d')+'.hdf5')

    if not os.path.exists(f):
        root = 'C:\\tdx\\tdx_7.46'
        trading_day = TradingDay(tdx_root=root)
        trading_day.reset()

        if trading_day.is_today_trading_day:
            
            msg = {'type':'function', 'function': 'check', 'args':[], 'kwargs':{'dt':now}}
            out = trading_day.send_processes_message(trading_day.hq_pipes, msg)
            trading_day.save()
                
        trading_day.stop_hq_processes()
        trading_day.stop_assist_process()
