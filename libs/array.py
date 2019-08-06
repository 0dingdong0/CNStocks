import pandas as pd
import numpy as np
from datetime import datetime
from datetime import timedelta
from collections import OrderedDict

from libs.utils import Utils

class D2Array(object):
    def __init__(self, rows, cols, buffer=None, dtype='<f4'):
        self.rows = rows
        self.cols = cols
        
        if buffer is not None:
            self.data = np.frombuffer(buffer, dtype=dtype)
            self.data = self.data.reshape((len(rows), len(cols)))
        else:
            self.data = np.empty((len(rows), len(cols)), dtype='<f4')
        # self.data.fill(np.nan)
        
    def as_df(self):
        return pd.DataFrame(data=self.data, index=self.rows, columns=self.cols)

class D3Array(object):

    def __init__(self, check_points, rows, cols, interval, buffer=None, dtype='<f4'):
        
        assert 60 % interval == 0
        
        self.interval = interval
        self.check_points = check_points
        self.rows = rows
        self.cols = cols
        
        if buffer is not None:
            self.data = np.frombuffer(buffer, dtype=dtype)
            self.data = self.data.reshape((len(check_points), len(rows), len(cols)))
        else:
            self.data = np.empty((len(self.check_points), len(rows), len(cols)), dtype=dtype)
        # self.data.fill(np.nan)
        
    def get_index(self, dt):
        result = int((dt-dt.replace(hour=9, minute=15, second=0, microsecond=0)).total_seconds())
        
        if result <= self.interval:
            return 0
        elif result < 600:
            index = int(result/self.interval)
            if result % self.interval != 0:
                return index
            else:
                return index-1
        elif result < 900:
            return int(600/self.interval)-1
        elif result == 900:
            return int(600/self.interval)
        elif result < 8100:
            result -= 300
            index = int((result)/self.interval)
            if result % self.interval != 0:
                return index
            else:
                return index-1
        elif result < 13500:
            return int(7800/self.interval)-1
        elif result == 13500:
            return int(7800/self.interval)
        elif result < 20700:
            result -= 5700
            index = int((result)/self.interval)
            if result % self.interval != 0:
                return index
            else:
                return index-1
        else:
            return int(15000/self.interval)-1

    def get_view(self, dt):
        idx = self.get_index(dt)
        return self.data[idx]