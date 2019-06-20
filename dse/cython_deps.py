# Copyright DataStax, Inc.
#
# Licensed under the DataStax DSE Driver License;
# you may not use this file except in compliance with the License.
#
# You may obtain a copy of the License at
#
# http://www.datastax.com/terms/datastax-dse-driver-license-terms

try:
    from dse.row_parser import make_recv_results_rows
    HAVE_CYTHON = True
except ImportError:
    HAVE_CYTHON = False

try:
    import numpy
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
