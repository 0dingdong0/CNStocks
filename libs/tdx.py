import os
import time
import math
import redis
import platform
import subprocess

from random import randrange
from pytdx.hq import TdxHq_API
from pytdx.params import TDXParams
from pytdx.config.hosts import hq_hosts as tdx_hq_hosts
from pytdx.reader import TdxDailyBarReader, TdxFileNotFoundException

from libs.utils import Utils

class TDX:
    
    def __init__(self, root):
        
        self.redis = redis.Redis(host='127.0.0.1', port=6379, decode_responses=True)
        self.root = root
        
        self.tdx = TdxHq_API(heartbeat=True, auto_retry=True)
        self.tdx_connect_to_server()
        self.tdx_hq_hosts = tdx_hq_hosts
    
    def ping(self, host):
    
        param = '-n' if platform.system().lower()=='windows' else '-c'
        command = ['ping', param, '1', host]

        start = time.time()
        subprocess.call(command)
        end = time.time()
        return (end - start)*1000
    
    def test_hosts(self):
        hosts = []
        for idx, host in enumerate(tdx_hq_hosts):
            print(str(idx+1)+'/'+str(len(tdx_hq_hosts))+' ping host:', host, end=", ")
            time = self.ping(host[1])
            print(time, 'ms')
            host = [*host]
            host.append(time)
            hosts.append(host)

        hosts.sort(key=lambda x : x[3])

        key = 'tdx_hosts'
        self.redis.delete(key)
        for host in hosts:
            if host[3] > 100:
                break
            self.redis.rpush(key, host[1]+':'+str(host[2]))
        return hosts
    
    def tdx_connect_to_server(self):
        key = 'tdx_hosts'
        
        if self.redis.exists("tdx_hosts") == 0:
            print('use default server: ', '202.108.253.130:7709')
            print('please run test_hosts to test out the fastest servers')
            self.tdx.connect('202.108.253.130', 7709)
        else:
            idx = -1
            selected = None
            min_time = None
            while True:
                idx += 1
                host = self.redis.lindex(key, idx)
                if host is None:
                    if selected is None:
                        print('use default server: ', '202.108.253.130:7709')
                        print('please run test_tdx_hosts to test out the fastest servers')
                        selected = ('202.108.253.130', 7709)
                    break

                host = host.split(':')
                print(host, end=", ")
                try:
                    time = self.ping(host[0])
                except Exception as e:
                    continue
                print('used', round(time,2), 'ms')

                if min_time is None or min_time > time:
                    min_time = time
                    selected = (host[0], int(host[1]))

            if min_time:
                print('selected:', selected, round(min_time, 2), 'ms')
            self.tdx.connect(*selected)
            
    def get_tdx_gainian(self):

        fname = os.path.join(self.root,'T0002', 'hq_cache', 'block_gn.dat')
        result = {}
        if type(fname) is not bytearray:
            with open(fname, "rb") as f:
                data = f.read()
        else:
            data = fname

        pos = 384
        (num, ) = struct.unpack("<H", data[pos: pos + 2])
        pos += 2
        for i in range(num):
            blockname_raw = data[pos: pos + 9]
            pos += 9
            name = blockname_raw.decode("gbk", 'ignore').rstrip("\x00")
            stock_count, block_type = struct.unpack("<HH", data[pos: pos + 4])
            pos += 4
            block_stock_begin = pos
            codes = []
            for code_index in range(stock_count):
                one_code = data[pos: pos + 7].decode("utf-8", 'ignore').rstrip("\x00")
                codes.append(one_code)
                pos += 7

            gn = {}
            gn["name"] = name
            gn["block_type"] = block_type
            gn["stock_count"] = stock_count
            gn["codes"] = codes
            result[name] = gn

            pos = block_stock_begin + 2800

        return result
    
    def get_tdx_hangye(self):

        file_hangye = os.path.join(self.root, 'incon.dat')
        assert os.path.exists(file_hangye)
        file_stock_hangye = os.path.join(self.tdx_dir, 'T0002', 'hq_cache',' tdxhy.cfg')
        assert os.path.exists(file_stock_hangye)

        result = {}
        with open(file_hangye, "rt", encoding='gb2312') as f:
            isTDXHY = False
            for line in f:
                line = line.rstrip()
                if not isTDXHY and line != '#TDXNHY':
                    continue
                elif not isTDXHY and line == '#TDXNHY':
                    isTDXHY = True
                    continue
                elif isTDXHY and line == '######':
                    isTDXHY = False
                    break
                code, name = line.split('|')
                result[code] = {}
                result[code]['code'] = code
                result[code]['name'] = name
                result[code]['codes'] = []

        with open(file_stock_hangye, "rt", encoding='gb2312') as f:
            for line in f:
                line = line.rstrip()
                market_code, stock_code, tdxhy_code, swhy_code, unknown_code = line.split("|")
                stock_code = stock_code.strip()

                if tdxhy_code != 'T00':
                    result[tdxhy_code]['codes'].append(stock_code)
        return result
    
    def get_tdx_zhishu(self):

        tdxzs_cfg = os.path.join(self.root, 'T0002', 'hq_cache', 'tdxzs.cfg')
        gainian = self.get_tdx_gainian()
        hangye = self.get_tdx_hangye()

        result = {}
        with open(tdxzs_cfg, "rt", encoding='gb2312') as f:
            for line in f:
                line = line.rstrip()
                zs_name, zs_code, zs_type, num_1, num_2, key = line.split('|')

                if key in gainian:
                    if zs_code in result:
                        print('------------------------------------------------------')
                        print('in result key: ', key, zs_name, zs_code)
                        print('gainian: ', key, gainian[key])
                        continue
                    else:
                        if len(gainian[key]['codes']) == 0:
                            continue
                        zs = {}
                        zs['code'] = zs_code
                        zs['name'] = gainian[key]['name']
                        zs['codes'] = gainian[key]['codes']
                        result[zs_code] = zs

                if key in hangye:
                    if zs_code in result:
                        print('------------------------------------------------------')
                        print('in result key: ', key, zs_name, zs_code)
                        print('hangye: ', key, hangye[key])
                        continue
                    else:
                        if len(hangye[key]['codes']) == 0:
                            continue
                        zs = {}
                        zs['code'] = zs_code
                        zs['name'] = hangye[key]['name']
                        zs['codes'] = hangye[key]['codes']
                        result[zs_code] = zs

        return result

    def is_tdx_local_data_ready_for(self, dt):
        file = os.path.join(self.root, 'vipdoc', 'sz', 'lday', 'sz399001.day')
        reader = TdxDailyBarReader()
        df = reader.get_df(file)

        return dt.strftime('%Y-%m-%d') in df.index
    
    def get_lastest_stock_codes(self):
        old_codes = Utils.get_stock_codes()
        code_filter = Utils.code_filter

        step_size = 1000
        codes = []
        for market in Utils.markets:

            count = self.tdx.get_security_count(market)
            print(market, count, end=' : ')

            steps = math.ceil(count/step_size)

            total = 0
            for step in range(steps):
                result = self.tdx.get_security_list(market, step_size*step)
                print(str(step)+'/'+str(steps), end=", ")
                for item in result:
                    code = item['code'].strip()
                    if code[:3] in code_filter[market]:
                        codes.append(code)
                        total += 1
            
            market_name = '深市' if market == 0 else '沪市'
            print(market_name + ' A股 总数: '+str(total))
        print('沪深 A股 总数:'+str(len(codes)))
        return codes