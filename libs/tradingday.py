from libs.utils import Utils
from libs.tdx import TDX
from libs.array import D2Array, D3Array
from libs.sina import Sina
from libs.hq import HQ

from multiprocessing.sharedctypes import RawArray
from multiprocessing import Process, Pipe

from datetime import datetime
from datetime import timedelta
from pyquery import PyQuery as pq

import os
import sys
import h5py
import json
import math
import time
import redis
import ctypes
import tushare
import numpy as np
# import asyncio

tushare.set_token('aecca28adc0d5a7764b748ccd48bef923d81314ae47b4d44d51fce67')

class TradingDay:
    tdx = None
    ts = tushare.pro_api()
    redis = redis.Redis(host='127.0.0.1', port=6379, decode_responses=True)
    concurrency = 8
    sub_group_count= 2
    
    date = None
    
    buffers = {}
    codes = None
    names = None
    msl = None
    fsl = None
    stat = None
    basics = None
    
    cache = {}

    hq_pipes = []
    hq_processes = []
    
    assist_pipe = None
    assist_process = None
    
    def __init__(self, tdx_root='', concurrency=8, sub_group_count=2):
        self.concurrency = concurrency
        self.sub_group_count = sub_group_count
        self.tdx_root = tdx_root
            
    def reset(self):
        TradingDay.tdx = TDX(self.tdx_root)
        now = datetime.now()
        ed = now.strftime('%Y%m%d')
        sd = (now - timedelta(days=30)).strftime('%Y%m%d')
        df = Utils.ts.trade_cal(exchange='', start_date=sd, end_date=ed)
        self.is_today_trading_day = df.iloc[-1,2] == 1
        if now <= now.replace(hour=9, minute=0, second=0, microsecond=0) or not self.is_today_trading_day:
            date = Utils.previous_trading_day(now)
        else:
            date = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if self.date is not None and self.date.strftime('%Y%m%d') == date.strftime('%Y%m%d'):
            print('hq was already initialized')
            return
            
        if not self.load(date):
            self.date = date
            if TradingDay.is_stock_codes_update_needed():
                codes = TradingDay.update_stock_codes()
                suspended = TradingDay.update_suspended_stock_codes()
            else:
                codes = Utils.get_stock_codes()
                suspended = Utils.get_suspended_stock_codes()
    
            codes = list(set(codes) - set(suspended))
            codes.sort()
            
            self.setup_arrays(codes)
            
            self.save(force=True)
        
        self.stop_hq_processes()
        self.create_hq_processes()
        self.start_hq_processes()
        
        self.stop_assist_process()
        self.create_assist_process()
        self.start_assist_process()
        
        if np.all(np.isnan(self.basics.data)):
            self.set_basics()

    def beat(self, dt=None):

        msg = {
            'type':'function', 
            'function': 'check', 
            'args':[], 
            'kwargs':{}
        }

        if dt is not None:
            msg['kwargs']['dt'] = dt.strftime('%Y-%m-%d %H:%M:%S')

        results = self.send_processes_message(self.hq_pipes, msg)
        # print('-->', results)
        # if any([result['type'] == 'exception' for result in results]):
        #     for idx, result in enumerate(results):
        #         if result['type'] == 'exception':
        #             print('hq process:', idx, 'failed')
        #             print(result['content'])
        #             print(result['traceback'])
        #     return

        if 'msl' not in results[0]:
            return

        msg = {
            'type':'function', 
            'function': 'incremental_save', 
            'args':[results[0]], 
            'kwargs':{}
        }
        self.send_processes_message([self.assist_pipe], msg, blocked=False)

    def setup_arrays(self, codes):
        self.buffers = {}
        codes.sort()
        codes_buffer = RawArray(ctypes.c_uint32, 6*len(codes))
        self.buffers['codes'] = codes_buffer
        self.codes = np.frombuffer(codes_buffer, dtype='<U6')
        self.codes[:] = codes
        
        ms = Sina(codes).market_snapshot()
        names_buffer = RawArray(ctypes.c_uint32, 4*len(ms))
        self.buffers['names'] = names_buffer
        self.names = np.frombuffer(names_buffer, dtype='<U4')
        self.names[:] = [ms[code]['name'] for code in codes]
        
        msl_interval = 5
        msl_check_points = Utils.get_check_points(msl_interval)
        msl_cols = ['open','close','now','high','low','turnover','volume']
        msl_buffer_size = int(len(msl_check_points)*len(codes)*len(msl_cols))
        msl_buffer = RawArray(ctypes.c_float, msl_buffer_size)
        self.buffers['msl'] = msl_buffer
        self.msl = D3Array(msl_check_points, codes, msl_cols, msl_interval, buffer=msl_buffer)   # market snapshots
        self.msl.data.fill(np.nan)
        
        fsl_interval = 60
        fsl_check_points = Utils.get_check_points(fsl_interval)
        fsl_cols = ['price','volume']
        fsl_buffer_size = int(len(fsl_check_points)*len(codes)*len(fsl_cols))
        fsl_buffer = RawArray(ctypes.c_float, fsl_buffer_size)
        self.buffers['fsl'] = fsl_buffer
        self.fsl = D3Array(fsl_check_points, codes, fsl_cols, fsl_interval, buffer=fsl_buffer)      # 分时 图
        self.fsl.data.fill(np.nan)
        
        stat_cols = ['zhangfu', 'junjia', 'liangbi', 'zhangsu', 'tingban', 'fsto']
        stat_buffer_size = int(len(fsl_check_points)*len(codes)*len(stat_cols))
        stat_buffer = RawArray(ctypes.c_float, stat_buffer_size)
        self.buffers['stat'] = stat_buffer
        self.stat = D3Array(fsl_check_points, codes, stat_cols, fsl_interval, buffer=stat_buffer)      # 分时 统计
        self.stat.data.fill(np.nan)
        
        basics_cols = ['zt_price', 'dt_price', 'ma5vpm', 'ltgb']
        basics_buffer_size = int(len(codes)*len(basics_cols))
        basics_buffer = RawArray(ctypes.c_float, basics_buffer_size)
        self.buffers['basics'] = basics_buffer
        self.basics = D2Array(codes, basics_cols, buffer=basics_buffer)      # 基本信息
        self.basics.data.fill(np.nan)
            
    def set_basics(self):
        
        # set zt_price
        returns = self.send_processes_message(self.hq_pipes, {
            'type':'function',
            'function': 'check',
            'args':[],
            'kwargs':{}
        })
        
        idx = returns[0]['msl']
        self.basics.data[:, 0] = np.around(self.msl.data[idx, :, 1]*1.1, decimals=2)
        self.basics.data[:, 1] = np.around(self.msl.data[idx, :, 1]*0.9, decimals=2)
        
        # set ma5vpm
        self.calculate_ma5vpm()
        
        # set ltgb
        dt = Utils.previous_trading_day(datetime.now())
        df = TradingDay.ts.daily_basic(trade_date=dt.strftime('%Y%m%d'))

        for index, code in enumerate(self.codes):
            scode = code+'.SH' if code[0] == '6' else code+'.SZ'
            result = df.loc[df['ts_code'] == scode,  'float_share']

            if len(result) == 0:
                continue

            self.basics.data[index, 3] = result.iloc[0]

    def create_hq_processes(self):
        
        group_size = math.ceil(len(self.codes)/self.concurrency)
        for idx in range(self.concurrency):
            scope = (idx*group_size, min((idx+1)*group_size,len(self.codes)))
            
            pipe = Pipe()
            parent, child = pipe
            self.hq_pipes.append(child)
            
            hq = HQ(self.date, pipe, self.buffers, scope, sub_group_count=self.sub_group_count)
            self.hq_processes.append(hq)

    def create_assist_process(self):
        pipe = Pipe()
        parent, child = pipe
        self.assist_pipe = child
        
        scope = (0, len(self.codes))
        self.assist_process = HQ(self.date, pipe, self.buffers, scope, sub_group_count=1)
            
    def start_hq_processes(self):
        for hq in self.hq_processes:
            hq.start()
            time.sleep(1)
            
        self.send_processes_message(self.hq_pipes, {
            'type':'function',
            'function': 'prepare',
            'args':[],
            'kwargs':{}
        })
        
    def start_assist_process(self):
        self.assist_process.start()
            
        self.send_processes_message([self.assist_pipe], {
            'type':'function',
            'function': 'prepare',
            'args':[],
            'kwargs':{}
        })

    def stop_hq_processes(self):
        if self.hq_pipes:
            self.send_processes_message(self.hq_pipes, {'type':'action', 'action':'quit'})
            self.hq_pipes = []
            self.hq_process = []
        
    def stop_assist_process(self):
        if self.assist_pipe:
            self.send_processes_message([self.assist_pipe], {'type':'action', 'action':'quit'})
            self.assist_pipe = None
            self.assist_process = None
    
    def send_processes_message(self, pipes, message, blocked=True):
            
        if not pipes or not pipes[0]:
            return None
        
        for pipe in pipes:
            while pipe.poll():
                pipe.recv()
            pipe.send(message)
        
        if not blocked:
            return None
        
        used_times = []
        returns = []
        for pipe in pipes:
            result = pipe.recv()
            if result['type'] == 'exception':
                print(result['content'])
                print(result['traceback'])
                # raise ValueError(result['content'])
            used_times.append(result['used_time'])
            returns.append(result['content'])
            
        content = message[message['type']]
        print('message['+content+'] used times:', used_times)
        return returns

    def save(self, dt=None, gzip_level=4, force=False):
        
        date = self.date if dt is None else dt
        
        folder = os.path.join(os.getcwd(), 'hdf5')
        if not os.path.exists(folder):
            os.mkdir(folder)

        key = date.strftime('%Y%m%d')
        file = os.path.join(folder, key + '.hdf5')
        now = datetime.now()
        if now.strftime('%Y%m%d') == key and not force:
            dt1 = now.replace(hour=9, minute=0, second=0, microsecond=0)
            dt2 = now.replace(hour=15, minute=0, second=30, microsecond=0)
            if dt1 <= now <= dt2:
                print('实时交易期间, 暂停 手动存盘, 系统会进行 自动 增量 存盘!')
                return
        
        if key == self.date.strftime('%Y%m%d'):
            
            if os.path.exists(file):
                print('文件 [', file, '] 已经存在，将被删除 ... ... ', end='')
                os.remove(file)
                print('已被删除')
                
            codes = np.char.encode(self.codes, encoding='utf-8')
            names = np.char.encode(self.names, encoding='utf-8')

            with h5py.File(file, "a") as f:
                f.create_dataset(u"codes", data=codes, compression="gzip", compression_opts=gzip_level)
                f.create_dataset(u"names", data=names, compression="gzip", compression_opts=gzip_level)

                f.create_dataset(u"msl", data=self.msl.data, compression="gzip", compression_opts=gzip_level)
                f.create_dataset(u"fsl", data=self.fsl.data, compression="gzip", compression_opts=gzip_level)
                f.create_dataset(u"stat", data=self.stat.data, compression="gzip", compression_opts=gzip_level)
                f.create_dataset(u"basics", data=self.basics.data, compression="gzip", compression_opts=gzip_level)

            print('行情 已经 写入文件：', file)
            
        elif key in self.cache:
            
            if os.path.exists(file):
                print('文件 [', file, '] 已经存在，将被删除 ... ... ', end='')
                os.remove(file)
                print('已被删除')
                
            cache = self.cache[key]
            codes = np.char.encode(cache['codes'], encoding='utf-8')
            names = np.char.encode(cache['names'], encoding='utf-8')

            with h5py.File(file, "a") as f:
                f.create_dataset(u"codes", data=codes, compression="gzip", compression_opts=gzip_level)
                f.create_dataset(u"names", data=names, compression="gzip", compression_opts=gzip_level)

                f.create_dataset(u"msl", data=cache['msl'].data, compression="gzip", compression_opts=gzip_level)
                f.create_dataset(u"fsl", data=cache['fsl'].data, compression="gzip", compression_opts=gzip_level)
                f.create_dataset(u"stat", data=cache['stat'].data, compression="gzip", compression_opts=gzip_level)
                f.create_dataset(u"basics", data=cache['basics'].data, compression="gzip", compression_opts=gzip_level)

            print('行情 已经 写入文件：', file)
        else:
            print('无法保存：', file)

    def push_in_cache(self):
        key = self.date.strftime('%Y%m%d')
        if key in self.cache:
            return
        
        cache = {}
        cache['buffers'] = self.buffers
        cache['codes'] = self.codes
        cache['names'] = self.names
        cache['msl'] = self.msl
        cache['fsl'] = self.fsl
        cache['stat'] = self.stat
        cache['basics'] = self.basics
        
        self.cache[key] = cache
    
    def restore_from_cache(self, dt):
        key = self.date.strftime('%Y%m%d')
        if key not in self.cache:
            self.push_in_cache()
        
        key = dt.strftime('%Y%m%d') if type(dt) is datetime else dt
            
        cache = self.cache[key]
        
        self.buffers = cache['buffers']
        self.codes = cache['codes']
        self.names = cache['names']
        self.msl = cache['msl']
        self.fsl = cache['fsl']
        self.stat = cache['stat']
        self.basics = cache['basics']
        
    def load(self, dt):
        
        key = dt.strftime('%Y%m%d') if type(dt) is datetime else dt
        
        if self.codes is not None and key not in self.cache:
            self.push_in_cache()
            
        # load from cache if it is in cache
        if key in self.cache:
            self.restore_from_cache(dt)
            return True
        
        file = os.path.join(os.getcwd(), 'hdf5', key + '.hdf5')
        if not os.path.exists(file):
            print('file['+file+'] does not exists!')
            return False
        
        if type(dt) is datetime:
            self.date = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            self.date = datetime.strptime(dt, "%Y%m%d")

        print('load from file:', file)    
        with h5py.File(file, "a") as f:
            
            codes = np.char.decode(f[u'codes'], 'utf-8')
            self.setup_arrays(codes)
            
            self.names[:] = np.char.decode(f[u'names'], 'utf-8')
            self.msl.data[:,:,:] = f[u'msl'][:,:,:]
            self.fsl.data[:,:,:] = f[u'fsl'][:,:,:]
            self.stat.data[:,:,:] = f[u'stat'][:,:,:]
            self.basics.data[:,:] = f[u'basics'][:,:]
        return True
    
    @staticmethod
    def reset_suspended_stock_codes():
        now = datetime.now()
        time1 = now.replace(hour=8, minute=45, second=0, microsecond=0)
        time2 = now.replace(hour=15, minute=0, second=0, microsecond=0)
        if time1<now<time2:
            print('请在8:30之前 或 15:05之后, 初始化 停牌股票')
            return

        suspended_codes = []
        market_snapshot = Sina(Utils.get_stock_codes()).market_snapshot()
        for code in market_snapshot:
            stock = market_snapshot[code]
            if stock['turnover'] == 0 and stock['close'] != 0:
                suspended_codes.append(code)

        Utils.save_suspended_stock_codes(suspended_codes)
        return suspended_codes
    
    @staticmethod
    def update_suspended_stock_codes():
        urls = [
            'http://stock.eastmoney.com/a/csstpyl.html',
            'http://stock.eastmoney.com/a/chstpyl.html'
        ]

        # loop = asyncio.get_event_loop()
        # results = loop.run_until_complete(Utils.fetch_all(urls))
        results = Utils.fetch_all(urls)

        redis_keys = ['suspended_sz_stocks_update_time', 'suspended_sh_stocks_update_time']
        update_dates = [None, None]
        hrefs = [[],[]]
        for index,result in enumerate(results):
            update_dates[index] = Utils.r.get(redis_keys[index])

            last_dt_str = ''
            doc = pq(result)
            for li in doc.find('#newsListContent li'):
                li = pq(li)
                dt_str = li.find('p.time').text().strip()

                print(update_dates[index], li.find('p.time').text().strip(), li.find('a').text())
                if not last_dt_str:
                    last_dt_str = dt_str

                if update_dates[index] is None:
                    hrefs[index].append(li.find('a').attr('href'))
                    break
                elif update_dates[index] == dt_str:
                    break
                else:
                    hrefs[index].append(li.find('a').attr('href'))

            update_dates[index] = last_dt_str

        if not hrefs[0] and not hrefs[1]:
            return Utils.get_suspended_stock_codes()

        items = []
        code_filter = Utils.code_filter
        
        for index, urls in enumerate(hrefs):
            # results = loop.run_until_complete(Utils.fetch_all(urls))
            results = Utils.fetch_all(urls)
            for result in results:
                suspended = []
                resumed = []

                doc = pq(result)
                for tr in doc.find('#ContentBody tr'):
                    tr = pq(tr)

                    code = tr.find('td:nth-child(1)').text()

                    if len(code)!=6 or code[:3] not in code_filter[index]:
                        continue

                    name = tr.find('td:nth-child(2)').text()
                    suspend_at = tr.find('td:nth-child(3)').text().strip()
                    resume_at = tr.find('td:nth-child(4)').text().strip()

                    if suspend_at:
                        suspended.append(code)
                    if resume_at:
                        resumed.append(code)

                items.append((suspended, resumed))

        print(items)
        suspended = []
        resumed = []
        for item in reversed(items):
            suspended = list(set(suspended).union(set(item[0])) - set(item[1]))
            resumed = list(set(resumed).union(set(item[1])))

        print('suspended:', suspended, 'resumed:', resumed)
        codes = Utils.get_suspended_stock_codes()
        suspended_codes = list(set(codes).union(set(suspended)) - set(resumed))
        Utils.save_suspended_stock_codes(suspended_codes)
        for index, key in enumerate(redis_keys):
            Utils.r.set(key, update_dates[index])

        return suspended_codes
    
    @staticmethod
    def update_stock_codes(force=False):
        
        old_codes = Utils.get_stock_codes()
        codes = TradingDay.tdx.get_lastest_stock_codes()
        stocks = Sina(codes).market_snapshot()
        
        unlisted = []
        for code in stocks:
            stock = stocks[code]
            if stock['close'] == 0 and not stock['name'].startswith('N'):
                unlisted.append(code)
                
        code_list = list(set(codes).intersection(set(stocks.keys())) - set(unlisted))
        code_list.sort()
        Utils.save_stock_codes(code_list)
        
        print('去掉 股票 代码：', set(old_codes)-set(code_list))
        print('新增 股票 代码：', set(code_list)-set(old_codes))
        TradingDay.redis.set('stock_codes_update_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        print('股票代码已更新, 总计：', len(code_list))
        return code_list
            
    @staticmethod
    def is_stock_codes_update_needed():
        update_dt = Utils.r.get('stock_codes_update_time')

        if not update_dt:
            return True

        # timezone = 'Asia/Shanghai'
        update_dt = datetime.strptime(update_dt, "%Y-%m-%d %H:%M:%S")

        now = datetime.now()
        if Utils.is_trading_day(now):
            compare_dt = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if now > compare_dt and update_dt < compare_dt:
                return True
            else:
                return False
        else:
            last_trading_day = Utils.previous_trading_day(now)
            compare_dt = last_trading_day.replace(hour=9, minute=0, second=0, microsecond=0)
            if update_dt <= compare_dt:
                return True
            else:
                return False
    
    def calculate_ma5vpm(self):
        print('calculating ma5vpm:')
        data = {}
        last_5_trading_days = Utils.last_5_trading_days()
        for dt in reversed(last_5_trading_days):
            
            key = dt.strftime('%Y%m%d')
            data[key] = {}
            
            if key == self.date.strftime('%Y%m%d'):
                data[key]['codes'] = self.codes
                data[key]['market_snapshot'] = self.msl.data[-1,:,:]
                print('\t', 'data['+key+'] was loaded directly')
            elif key in self.cache:
                data[key]['codes'] = self.cache['codes']
                data[key]['market_snapshot'] = self.cache['msl'].data[-1,:,:]
                print('\t', 'data['+key+'] was loaded from cache')
            else:
                file = os.path.join(os.getcwd(), 'hdf5', key + '.hdf5')
                assert os.path.exists(file)

                data[key] = {}
                with h5py.File(file, "r") as f:
                    data[key]['codes'] = np.char.decode(f[u'codes'], 'utf-8')
                    data[key]['market_snapshot'] = np.copy(f[u'msl'][-1,:,:])
                print('\t', 'data['+key+'] was loaded from', file)

        dt_str = self.date.strftime('%Y-%m-%d')
        for index, symbol in enumerate(self.codes):

            redis_key = symbol+"_ma5vpm"

            sum_vol = 0
            count = 0
            for key in data:

                symbols = data[key]['codes']

                if symbol not in symbols:
                    break

                idx = np.where(symbols==symbol)[0][0]
                ms = data[key]['market_snapshot']

                turnover = ms[idx, 5]
                if turnover == 0:
                    sum_vol = 0
                    break
                else:
                    sum_vol += turnover
                    count += 1

            if sum_vol != 0:
                self.basics.data[index, 2] = sum_vol/(240*count)
                if TradingDay.redis.exists(redis_key):
                    TradingDay.redis.delete(redis_key)
            elif count == 0 and TradingDay.redis.exists(redis_key):
                self.basics.data[index, 2] = float(TradingDay.redis.get(redis_key))
                print('\t', index, symbol, 'was from redis')
            else:
                print('\t', index, symbol, 'try online-loading from Sina', end=' ... ')
                klines = Sina.kline([symbol], length=6)[symbol]
                if klines:
                    ma5vpm = 0
                    sum_vol = 0
                    count = 0
                    for kline in reversed(klines):
                        if kline['day'] == dt_str:
                            continue

                        if 'ma_volume5' in kline:
                            ma5vpm = kline['ma_volume5']/240
                            break
                        else:
                            sum_vol += int(kline['volume'])
                            count += 1
                            if count == 5:
                                break

                    if ma5vpm != 0:
                        self.basics.data[index, 2] = ma5vpm
                        TradingDay.redis.set(redis_key, ma5vpm)
                        print('done!')
                    elif sum_vol != 0:
                        self.basics.data[index, 2] = sum_vol/(240*count)
                        TradingDay.redis.set(redis_key, ma5vpm)
                        print('done! new listed stock with', str(count), 'candles!')
                    else:
                        print('brand new listed stock?!')
                else:
                    print('unlisted?!')
        print('\t finished!')

    def memory_usage(self):
        buffers = [self.buffers]
        for key in self.cache:
            buffers.append(self.cache[key]['buffers'])
            
        summe = 0
        for buffer in buffers:
            for key in buffer:
                obj = buffer[key]
                summe += len(obj) * ctypes.sizeof(obj._type_)
        return summe/(1024*1024)
