from datetime import timedelta
from datetime import datetime

from pytdx.hq import TdxHq_API
from pytdx.params import TDXParams
from pytdx.config.hosts import hq_hosts as tdx_hq_hosts
from pytdx.reader import TdxDailyBarReader, TdxFileNotFoundException

from threading import Thread

import re
import os
import json
import redis
import aiohttp
import asyncio
# import nest_asyncio
import tushare as TS

# nest_asyncio.apply()

class Utils:

    headers = {
        "Accept-Encoding": "gzip, deflate, sdch",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/54.0.2840.100 "
            "Safari/537.36"
        ),
    }

    r = redis.Redis(host='127.0.0.1', port=6379, decode_responses=True)
    ts = TS.pro_api('aecca28adc0d5a7764b748ccd48bef923d81314ae47b4d44d51fce67')

    STOCK_CODES_FILE = os.path.join(os.getcwd(), "stock_codes.json")
    SUSPENDED_STOCK_CODES_FILE = os.path.join(os.getcwd(), "suspended_stock_codes.json")

    # 0: sz
    # 1: sh
    markets = [0, 1]
    code_filter = [
        ['000', '001', '002', '300'],
        ['600', '601', '603', '688']
    ]

    @staticmethod
    def get_check_points(interval):
        td = timedelta(seconds=interval)

        check_points = []

        trading_times = [
            ['0915', '0925'],
            ['0930', '1130'],
            ['1300', '1500'],
        ]

        now = datetime.now()
        for time_range in trading_times:
            start = now.replace(hour=int(time_range[0][:2]), minute=int(time_range[0][2:]), second=0, microsecond=0)
            end = now.replace(hour=int(time_range[1][:2]), minute=int(time_range[1][2:]), second=0, microsecond=0)

            t = start
            while t<end:
                check_points.append(t.strftime('%H:%M:%S'))
                t += td
                
        return check_points
    
    @staticmethod
    def last_5_trading_days(dt=None):
        if dt is None:
            dt = datetime.now()    
        ed = dt.strftime('%Y%m%d')
        td = timedelta(days=30)
        sd = (dt-td).strftime('%Y%m%d')
        df = Utils.ts.trade_cal(exchange='', start_date=sd, end_date=ed)
        
        pdays = []
        idx = df.index[df['cal_date'] == ed][0]
        while True:
            idx -= 1
            if df.iloc[idx, 2] == 1:
                pdstr = df.iloc[idx, 1]
                pdays.insert(0, datetime.strptime(pdstr, '%Y%m%d'))
                
                if len(pdays) == 5:
                    break
            else:
                continue
        return pdays
    
    @staticmethod
    def previous_trading_day(dt, df=None):
        if df is None:
            ed = dt.strftime('%Y%m%d')
            td = timedelta(days=30)
            sd = (dt-td).strftime('%Y%m%d')
            df = Utils.ts.trade_cal(exchange='', start_date=sd, end_date=ed)
        
        pdstr = ''
        idx = df.index[df['cal_date'] == dt.strftime('%Y%m%d')][0]
        while True:
            idx -= 1
            if df.iloc[idx, 2] == 1:
                pdstr = df.iloc[idx, 1]
                break
            else:
                continue
        return datetime.strptime(pdstr, '%Y%m%d')
    
    @staticmethod
    def next_trading_day(dt, df=None):
        if df is None:
            sd = dt.strftime('%Y%m%d')
            td = timedelta(days=30)
            ed = (dt+td).strftime('%Y%m%d')
            df = Utils.ts.trade_cal(exchange='', start_date=sd, end_date=ed)
        
        ndstr = ''
        idx = df.index[df['cal_date'] == dt.strftime('%Y%m%d')][0]
        while True:
            idx += 1
            if df.iloc[idx, 2] == 1:
                ndstr = df.iloc[idx, 1]
                break
            else:
                continue
        return datetime.strptime(ndstr, '%Y%m%d')

    @staticmethod
    def is_trading_day(dt):
        sd = dt.strftime('%Y%m%d')
        ed = sd
        df = Utils.ts.trade_cal(exchange='', start_date=sd, end_date=ed)
        if df.loc[df['cal_date']==sd].iloc[0,2] == 0:
            return False
        else:
            return True

    @staticmethod
    def get_stock_codes():
        if not os.path.exists(Utils.STOCK_CODES_FILE):
            return []

        with open(Utils.STOCK_CODES_FILE) as f:
            return json.load(f)

    @staticmethod
    def save_stock_codes(codes):
        codes.sort()
        with open(Utils.STOCK_CODES_FILE, "w") as f:
            f.write(json.dumps(codes))
        
    @staticmethod
    def get_suspended_stock_codes():
        if not os.path.exists(Utils.SUSPENDED_STOCK_CODES_FILE):
            return None

        with open(Utils.SUSPENDED_STOCK_CODES_FILE) as f:
            return json.load(f)

    @staticmethod
    def save_suspended_stock_codes(codes):
        codes.sort()
        with open(Utils.SUSPENDED_STOCK_CODES_FILE, "w") as f:
            f.write(json.dumps(codes))

    @staticmethod
    async def async_fetch(session, url):
        async with session.get(url, headers=Utils.headers) as response:
            return await response.text()
        
    # @staticmethod
    # async def fetch_all(urls):
        
    #     assert urls

    #     tasks = []
    #     async with aiohttp.ClientSession() as session:
    #         for url in urls:
    #             tasks.append(Utils.fetch(session, url))
    #         return await asyncio.gather(*tasks)
              
    @staticmethod
    async def async_fetch_all(urls):
        async with aiohttp.ClientSession() as session:
            return await asyncio.gather(*[Utils.async_fetch(session, url) for url in urls])

    @staticmethod
    def fetch_all(urls):
        loop = asyncio.get_event_loop_policy()._local._loop
        if loop and loop.is_running():
            print('using asyncio in a new thread')
            thread = ThreadedAsyncio(target=Utils.async_fetch_all, args=(urls,))
            thread.start()
            return thread.join()
        else:
            print('using asyncio in current thread')
            return asyncio.run(Utils.async_fetch_all(urls))

class ThreadedAsyncio(Thread):
    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}):
        Thread.__init__(self, group, target, name, args, kwargs)
        self._return = None
        
    def run(self):
        self._return = asyncio.run(self._target(*self._args, **self._kwargs))

    def join(self, *args):
        Thread.join(self, *args)
        return self._return