# Copyright DataStax, Inc.
#
# Licensed under the DataStax DSE Driver License;
# you may not use this file except in compliance with the License.
#
# You may obtain a copy of the License at
#
# http://www.datastax.com/terms/datastax-dse-driver-license-terms

import six


# Caching constants.
CACHING_ALL = "ALL"
CACHING_KEYS_ONLY = "KEYS_ONLY"
CACHING_ROWS_ONLY = "ROWS_ONLY"
CACHING_NONE = "NONE"


class CQLEngineException(Exception):
    pass


class ValidationError(CQLEngineException):
    pass


class UnicodeMixin(object):
    if six.PY3:
        __str__ = lambda x: x.__unicode__()
    else:
        __str__ = lambda x: six.text_type(x).encode('utf-8')
