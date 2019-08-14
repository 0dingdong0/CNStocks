import numpy as np
cimport numpy as np
cimport cython
from libc.math cimport isnan

ctypedef np.float32_t DTYPE_t

@cython.boundscheck(False)
@cython.cdivision
@cython.wraparound(False)
cpdef compute_stats(DTYPE_t[:,:] ms, DTYPE_t[:,:] fs, DTYPE_t[:,:] b, DTYPE_t[:,:] st, DTYPE_t[:,:] ms1p, DTYPE_t[:,:] fs5p, Py_ssize_t index_fs):
    
    # ms
    cdef Py_ssize_t idx_open = 0
    cdef Py_ssize_t idx_now = 2
    cdef Py_ssize_t idx_close = 1
    cdef Py_ssize_t idx_turnover = 5
    cdef Py_ssize_t idx_volume = 6
    
    cdef Py_ssize_t idx_zf = 0
    cdef Py_ssize_t idx_jj = 1
    cdef Py_ssize_t idx_lb = 2
    cdef Py_ssize_t idx_zs = 3
    cdef Py_ssize_t idx_zt = 4
    cdef Py_ssize_t idx_fsto = 5
    
    cdef Py_ssize_t rows = ms.shape[0]
    cdef Py_ssize_t cols = ms.shape[1]
    
    cdef Py_ssize_t interval = min(index_fs - 9, 1)
    
    cdef list indices_zt = []
    for i in range(rows):
        
        fs[i,0] = ms[i,2]
        if index_fs == 0:
            fs[i,1] = ms[i,5]
        else:
            fs[i,1] = ms[i,5] - ms1p[i,5]
        
        if ms[i,idx_open]:
            st[i,idx_zf] = 100*(ms[i,idx_now]/ms[i,idx_close]-1)

        if ms[i,idx_turnover]:
            st[i,idx_jj] = ms[i,idx_volume]/ms[i,idx_turnover]
            st[i,idx_zs] = 100*(ms[i,idx_now]/fs5p[i, 0]-1)
            if ms[i,idx_now] - b[i,0] > -0.0001:
                indices_zt.append(i)

        if b[i,2] and ms[i,idx_turnover]:
            st[i,idx_lb] = ms[i,idx_turnover]/interval/b[i,2]

    return indices_zt