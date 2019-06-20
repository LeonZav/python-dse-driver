# Copyright DataStax, Inc.
#
# Licensed under the DataStax DSE Driver License;
# you may not use this file except in compliance with the License.
#
# You may obtain a copy of the License at
#
# http://www.datastax.com/terms/datastax-dse-driver-license-terms

from dse.bytesio cimport BytesIOReader
from dse.deserializers cimport Deserializer

cdef class ParseDesc:
    cdef public object colnames
    cdef public object coltypes
    cdef Deserializer[::1] deserializers
    cdef public int protocol_version
    cdef Py_ssize_t rowsize

cdef class ColumnParser:
    cpdef parse_rows(self, BytesIOReader reader, ParseDesc desc)

cdef class RowParser:
    cpdef unpack_row(self, BytesIOReader reader, ParseDesc desc)

