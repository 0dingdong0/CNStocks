from libs.utils import Utils

import re
import os
import math
import json
import random
# import asyncio
import numpy as np
import pandas as pd


np.set_printoptions(formatter={'float': lambda x: "{0:0.2f}".format(x)})
pd.options.display.float_format = '{:,.2f}'.format

class Sina:
    max_group_size = 800
    
    def __init__(self, codes, group_count=1):
        
        self.codes = codes
        
        codes_size = len(codes)
        
        min_group_count = math.ceil(codes_size/self.max_group_size)
        if group_count < min_group_count:
            self.group_count =  min_group_count
        else:
            self.group_count = group_count
            
        self.group_size = math.ceil(codes_size/self.group_count)
        
        codes_with_prefix = list(map(lambda x: 'sh'+x[-6:] if x[0]=='6' else 'sz'+x[-6:], self.codes))
        
        self.code_lists = list([
            ','.join(
                codes_with_prefix[idx*self.group_size:min((idx+1)*self.group_size, codes_size)]
            ) for idx in range(self.group_count)
        ])
        
        # print('process id:', os.getpid(), self.group_count, self.group_size)
        
    @property
    def stock_api(self) -> str:
        return f"http://hq.sinajs.cn/rn={self._random()}&list="
    
    @staticmethod
    def _random(length=13) -> str:
        start = 10 ** (length - 1)
        end = (10 ** length) - 1
        return str(random.randint(start, end))
        
    def parse_real_data(self, data_str, length, array=None):
    
        # grep_detail_with_prefix = re.compile(
        #     r'(\w{2}\d+)="([^,=]+)%s%s'
        #     % (r',([\.\d]+)' * 29, r',([-\.\d:]+)' * 2)
        # )

        grep_str = re.compile(
            r'(\d+)="([^,=]+)%s%s'
            % (r",([\.\d]+)" * 29, r",([-\.\d:]+)" * 2)
        )
    
        results = grep_str.finditer(data_str)
        
        if array is not None:
            idx = -1
            for stock_match_object in results:
                idx += 1
                stock = stock_match_object.groups()

                array[idx, 0] = stock[2]   # open
                array[idx, 1] = stock[3]   # close
                array[idx, 2] = stock[4]   # now
                array[idx, 3] = stock[5]   # high
                array[idx, 4] = stock[6]   # low
                array[idx, 5] = stock[9]   # turnover
                array[idx, 6] = stock[10]   # volume
                
            assert (idx+1) == length
        else:
            stock_dict = dict()
            for stock_match_object in results:
                stock = stock_match_object.groups()
                stock_dict[stock[0]] = dict(
                    name=stock[1],
                    open=float(stock[2]),
                    close=float(stock[3]),
                    now=float(stock[4]),
                    high=float(stock[5]),
                    low=float(stock[6]),
                    buy=float(stock[7]),
                    sell=float(stock[8]),
                    turnover=int(stock[9]),
                    volume=float(stock[10]),
                    bid1_volume=int(stock[11]),
                    bid1=float(stock[12]),
                    bid2_volume=int(stock[13]),
                    bid2=float(stock[14]),
                    bid3_volume=int(stock[15]),
                    bid3=float(stock[16]),
                    bid4_volume=int(stock[17]),
                    bid4=float(stock[18]),
                    bid5_volume=int(stock[19]),
                    bid5=float(stock[20]),
                    ask1_volume=int(stock[21]),
                    ask1=float(stock[22]),
                    ask2_volume=int(stock[23]),
                    ask2=float(stock[24]),
                    ask3_volume=int(stock[25]),
                    ask3=float(stock[26]),
                    ask4_volume=int(stock[27]),
                    ask4=float(stock[28]),
                    ask5_volume=int(stock[29]),
                    ask5=float(stock[30]),
                    date=stock[31],
                    time=stock[32],
                )
                
            return stock_dict
        
    def market_snapshot(self, array=None):
        urls = [self.stock_api + stock_list for stock_list in self.code_lists]

        # loop = asyncio.get_event_loop()
        # result = loop.run_until_complete(Utils.fetch_all(urls))
        result = Utils.fetch_all(urls)
        return self.parse_real_data(''.join(result), len(self.codes), array=array)
        
    def real(self, codes, group_count=None, array=None):
        length = len(codes)
        codes_with_prefix = list(map(lambda x: 'sh'+x[-6:] if x[0]=='6' else 'sz'+x[-6:], codes))
            
        if group_count is None:
            group_size = self.max_group_size
            group_count = math.ceil(length/group_size)
        else:
            min_group_count = math.ceil(length/self.max_group_size)
            if group_count < min_group_count:
                group_count =  min_group_count
                
            group_size = math.ceil(length/group_count)
        
        code_lists = list([
            ','.join(
                codes_with_prefix[idx*group_size:min((idx+1)*group_size, length)]
            ) for idx in range(self.group_count)
        ])
        
        urls = [self.stock_api + stock_list for stock_list in code_lists]

        # loop = asyncio.get_event_loop()
        # result = loop.run_until_complete(Utils.fetch_all(urls))
        result = Utils.fetch_all(urls)
        return self.parse_real_data(''.join(result), len(self.codes), array=array)

    @staticmethod
    def kline(codes, scale=240, ma=5, length=1023):

        args = (scale, ma, length)
        url = 'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/' \
              'CN_MarketData.getKLineData?symbol={}&scale={}&ma={}&datalen={}'
        urls = list(map(
            lambda x: url.format('sh'+x[-6:], *args) if x[0]=='6' else \
                      url.format('sz'+x[-6:], *args),
            codes
        ))

        # loop = asyncio.get_event_loop()
        # results = loop.run_until_complete(Utils.fetch_all(urls))
        results = Utils.fetch_all(urls)

        klines = list(map(
            lambda x: json.loads(re.sub('(\w+)\s?:\s?("?[^",]+"?,?)', "\"\g<1>\":\g<2>", x)),
            results
        ))

        stocks = {}
        for idx, code in enumerate(codes):
            stocks[code] = klines[idx]

        return stocks