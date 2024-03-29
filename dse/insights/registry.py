from dse.insights.util import namespace

import six

from collections import OrderedDict
import traceback
from warnings import warn

_NOT_SET = object()


def _default_serializer_for_object(obj, policy):
    # the insights server expects an 'options' dict for policy
    # objects, but not for other objects
    if policy:
        return {'type': obj.__class__.__name__,
                'namespace': namespace(obj.__class__),
                'options': {}}
    else:
        return {'type': obj.__class__.__name__,
                'namespace': namespace(obj.__class__)}


class InsightsSerializerRegistry(object):

    initialized = False

    def __init__(self, mapping_dict=None):
        mapping_dict = mapping_dict or {}
        class_order = self._class_topological_sort(mapping_dict)
        self._mapping_dict = OrderedDict(
            ((cls, mapping_dict[cls]) for cls in class_order)
        )

    def serialize(self, obj, policy=False, default=_NOT_SET, cls=None):
        try:
            return self._get_serializer(cls if cls is not None else obj.__class__)(obj)
        except Exception:
            if default is _NOT_SET:
                result = _default_serializer_for_object(obj, policy)
            else:
                result = default

            return result

    def _get_serializer(self, cls):
        try:
            return self._mapping_dict[cls]
        except KeyError:
            for registered_cls, serializer in six.iteritems(self._mapping_dict):
                if issubclass(cls, registered_cls):
                    return self._mapping_dict[registered_cls]
        raise ValueError

    def register(self, cls, serializer):
        self._mapping_dict[cls] = serializer
        self._mapping_dict = OrderedDict(
            ((cls, self._mapping_dict[cls])
             for cls in self._class_topological_sort(self._mapping_dict))
        )

    def register_serializer_for(self, cls):
        """
        Parameterized registration helper decorator. Given a class `cls`,
        produces a function that registers the decorated function as a
        serializer for it.
        """
        def decorator(serializer):
            self.register(cls, serializer)
            return serializer

        return decorator

    @staticmethod
    def _class_topological_sort(classes):
        """
        A simple topological sort for classes. Takes an iterable of class objects
        and returns a list A of those classes, ordered such that A[X] is never a
        superclass of A[Y] for X < Y.

        This is an inefficient sort, but that's ok because classes are infrequently
        registered. It's more important that this be maintainable than fast.

        We can't use `.sort()` or `sorted()` with a custom `key` -- those assume
        a total ordering, which we don't have.
        """
        unsorted, sorted_ = list(classes), []
        while unsorted:
            head, tail = unsorted[0], unsorted[1:]

            # if head has no subclasses remaining, it can safely go in the list
            if not any(issubclass(x, head) for x in tail):
                sorted_.append(head)
            else:
                # move to the back -- head has to wait until all its subclasses
                # are sorted into the list
                tail.append(head)

            unsorted = tail

        # check that sort is valid
        for i, head in enumerate(sorted_):
            for after_head_value in sorted_[(i + 1):]:
                if issubclass(after_head_value, head):
                    warn('Sorting classes produced an invalid ordering.\n'
                         'In:  {classes}\n'
                         'Out: {sorted_}'.format(classes=classes, sorted_=sorted_))
        return sorted_


insights_registry = InsightsSerializerRegistry()
