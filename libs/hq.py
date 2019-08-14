from libs.sina import Sina
from libs.utils import Utils
from libs.array import D2Array, D3Array
from libs.cython.compute import compute_stats

from timeit import default_timer as timer
from multiprocessing import Process, Pipe

from datetime import datetime
from datetime import timedelta

import os
import h5py
import traceback
import numpy as np

class HQ(Process):
    
    def __init__(self, date, pipe, buffers, scope=None, sub_group_count=1):
        super(HQ, self).__init__()

        self.allowed_funcs = ['prepare', 'check', 'incremental_save', 'close_hdf5']
        
        self.date = datetime.strptime(date, '%Y-%m-%d') if type(date) == str else date

        parent, child = pipe
        # child.close()
        self.parent = parent

        self.buffers = buffers
        self.scope = scope
        self.sub_group_count = sub_group_count

        self.file_hdf5 = None
        
        print('hq process ['+str(self.pid)+'] was started with scope:', scope, 'and sub_group_count:', sub_group_count)

    def run(self):
        while True:
            try:
                msg = self.parent.recv()
                
                start = timer()
                
                result = {'pid': os.getpid()}

                if msg['type'] == 'action' and msg['action'] == 'quit':
                    if self.file_hdf5:
                        self.file_hdf5.close()

                    result['type'] = 'notification'
                    result['content'] = 'this process is going to quit!'
                    break
                    
                elif msg['type'] == 'function':
                    
                    func = msg['function']

                    if hasattr(self, func) and func in self.allowed_funcs:
                        args = msg['args']
                        kwargs = msg['kwargs']
                        result['content'] = getattr(self, func)(*args, **kwargs)
                        result['type'] = 'return'

                    elif func in self.allowed_funcs:
                        result['type'] = 'exception'
                        result['content'] = 'Call to func['+func+'] is not allowed!'
                        result['traceback'] = ''
                        
                    else:
                        result['type'] = 'exception'
                        result['content'] = 'func['+func+'] does not exist!'
                        result['traceback'] = ''
                    
                else:
                    result['type'] = 'exception'
                    result['content'] = 'stupid input message'
                    result['traceback'] = ''
                        
            except EOFError as e:
                result['type'] = 'notification'
                result['content'] = 'pipe connection was closed and this process is going to quit!'
                break
            except Exception as e:
                result['type'] = 'exception'
                result['content'] = str(e)
                result['traceback'] = traceback.format_exc()
            finally:
                result['used_time'] = timer()-start
                self.parent.send(result)
    
    def check(self, dt=None):
        if dt:
            dtime = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S') if type(dt) is str else dt
        else:
            dtime = datetime.now()

        msl_idx = self.msl.get_index(dtime)
        ms = self.msl.data[msl_idx, self.scope[0]:self.scope[1], :]

        self.sina.market_snapshot(array=ms)

        fsl_idx = self.fsl.get_index(dtime)
        fs = self.fsl.data[fsl_idx, self.scope[0]:self.scope[1], :]

        b = self.basics.data[self.scope[0]:self.scope[1], :]
        st = self.stat.data[fsl_idx, self.scope[0]:self.scope[1], :]


        t0925 = dtime.replace(hour=9, minute=25, second=0, microsecond=0)
        t0930 = dtime.replace(hour=9, minute=30, second=0, microsecond=0)
        t1130 = dtime.replace(hour=11, minute=30, second=0, microsecond=0)
        t1300 = dtime.replace(hour=13, minute=0, second=0, microsecond=0)
        t1500 = dtime.replace(hour=15, minute=0, second=0, microsecond=0)
        if t0925<dtime<=t0930:
            dtime = t0925
        elif t1130<dtime<=t1300:
            dtime = t1130
        elif t1500<dtime:
            dtime = t1500
        pmdt = (dtime - timedelta(seconds=1)).replace(second=0, microsecond=0)
        msl1p_idx = self.msl.get_index(pmdt)
        ms1p = self.msl.data[msl1p_idx, self.scope[0]:self.scope[1], :]

        fsl5p_idx = min(fsl_idx - 5, 9)
        fs5p = self.fsl.data[fsl5p_idx, self.scope[0]:self.scope[1], :]

        compute_stats(ms, fs, b, st, ms1p, fs5p, fsl_idx)
        # # set fsl
        # fsl_idx = self.fsl.get_index(dtime)
        # fsl_view = self.fsl.data[fsl_idx, self.scope[0]:self.scope[1], :]
        # # set price in fsl
        # fsl_view[:,0] = msl_view[:,2]
        # #set volume in fsl
        # if fsl_idx == 0:
        #     fsl_view[:,1] = msl_view[:,5]
        # else:
        #     #上一分钟结束时的 快照表 的 idx
        #     pmdt = (dtime - timedelta(seconds=1)).replace(second=0, microsecond=0)
        #     pmsl_idx = self.msl.get_index(pmdt)
        #     #上一分钟结束时的 快照表 的 turnover
        #     pms_turnover = self.msl.data[pmsl_idx, self.scope[0]:self.scope[1], 5]
        #     fsl_view[:,1] = msl_view[:,5] - pms_turnover
        # # if pmsl_idx == 0:
        # #     fsl_view[:,1] = msl_view[:,5]
        # # else:
        # #     pms_turnover = self.msl.data[msl_idx, self.scope[0]:self.scope[1], 5]
        # #     fsl_view[:,1] = msl_view[:,5] - pms_turnover
        return {'msl':msl_idx, 'fsl':fsl_idx}

    def prepare(self):
        buffers = self.buffers
        scope = self.scope
        sub_group_count = self.sub_group_count

        self.codes = np.frombuffer(buffers['codes'], dtype='<U6')
        self.names = np.frombuffer(buffers['names'], dtype='<U4')
        
        # 快照 数据
        msl_interval = 5
        msl_check_points = Utils.get_check_points(msl_interval)
        msl_cols = ['open','close','now','high','low','turnover','volume']
        self.msl = D3Array(msl_check_points, self.codes, msl_cols, msl_interval, buffer=buffers['msl'])   # market snapshots
        
        # 分时 数据
        fsl_interval = 60
        fsl_check_points = Utils.get_check_points(fsl_interval)
        fsl_cols = ['price','volume']
        self.fsl = D3Array(fsl_check_points, self.codes, fsl_cols, fsl_interval, buffer=buffers['fsl'])      # 分时 图
        
        # 统计 数据
        stat_cols = ['zhangfu', 'junjia', 'liangbi', 'zhangsu', 'fszb', 'fsto']
        self.stat = D3Array(fsl_check_points, self.codes, stat_cols, fsl_interval, buffer=buffers['stat'])      # 分时 统计
        
        # 基本 信息
        basics_cols = ['zt_price', 'ma5vpm', 'ltgb']
        self.basics = D2Array(self.codes, basics_cols, buffer=buffers['basics'])

        if scope is None:
            self.sina = Sina(self.codes, group_count=sub_group_count)
        else:
            self.sina = Sina(self.codes[scope[0]:scope[1]], group_count=sub_group_count)

    def incremental_save(self, indices):
        if self.file_hdf5 is None:
            file = os.path.join(os.getcwd(), 'hdf5', self.date.strftime('%Y%m%d')+'.hdf5')

            if not os.path.exists(file):
                return 'file['+file+'] does not exists!'

            self.file_hdf5 = h5py.File(file, 'r+')

        self.file_hdf5[u'msl'][indices['msl']] = self.msl.data[indices['msl']]
        self.file_hdf5[u'fsl'][indices['fsl']] = self.fsl.data[indices['fsl']]
        self.file_hdf5.flush()
        return "data was incremental saved"

    def close_hdf5(self):
        if self.file_hdf5 is None:
            return "no file needs to be closed"
        self.file_hdf5.close()
        self.file_hdf5 = None
        return "hdf5 file was closed"
