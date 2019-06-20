# Copyright DataStax, Inc.
#
# Licensed under the DataStax DSE Driver License;
# you may not use this file except in compliance with the License.
#
# You may obtain a copy of the License at
#
# http://www.datastax.com/terms/datastax-dse-driver-license-terms

cdef class BytesIOReader:
    cdef bytes buf
    cdef char *buf_ptr
    cdef Py_ssize_t pos
    cdef Py_ssize_t size
    cdef char *read(self, Py_ssize_t n = ?) except NULL
