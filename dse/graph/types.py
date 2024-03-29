# Copyright DataStax, Inc.
#
# Licensed under the DataStax DSE Driver License;
# you may not use this file except in compliance with the License.
#
# You may obtain a copy of the License at
#
# http://www.datastax.com/terms/datastax-dse-driver-license-terms


class Element(object):

    element_type = None

    _attrs = ('id', 'label', 'type', 'properties')

    def __init__(self, id, label, type, properties):
        if type != self.element_type:
            raise TypeError("Attempted to create %s from %s element", (type, self.element_type))

        self.id = id
        self.label = label
        self.type = type
        self.properties = self._extract_properties(properties)

    @staticmethod
    def _extract_properties(properties):
        return dict(properties)

    def __eq__(self, other):
        return all(getattr(self, attr) == getattr(other, attr) for attr in self._attrs)

    def __str__(self):
        return str(dict((k, getattr(self, k)) for k in self._attrs))


class Vertex(Element):
    """
    Represents a Vertex element from a graph query.

    Vertex ``properties`` are extracted into a ``dict`` of property names to list of :class:`~VertexProperty` (list
    because they are always encoded that way, and sometimes have multiple cardinality; VertexProperty because sometimes
    the properties themselves have property maps).
    """

    element_type = 'vertex'

    @staticmethod
    def _extract_properties(properties):
        # vertex properties are always encoded as a list, regardless of Cardinality
        return dict((k, [VertexProperty(k, p['value'], p.get('properties')) for p in v]) for k, v in properties.items())

    def __repr__(self):
        properties = dict((name, [{'label': prop.label, 'value': prop.value, 'properties': prop.properties} for prop in prop_list])
                          for name, prop_list in self.properties.items())
        return "%s(%r, %r, %r, %r)" % (self.__class__.__name__,
                                       self.id, self.label,
                                       self.type, properties)


class VertexProperty(object):
    """
    Vertex properties have a top-level value and an optional ``dict`` of properties.
    """

    label = None
    """
    label of the property
    """

    value = None
    """
    Value of the property
    """

    properties = None
    """
    dict of properties attached to the property
    """

    def __init__(self, label, value, properties=None):
        self.label = label
        self.value = value
        self.properties = properties or {}

    def __eq__(self, other):
        return isinstance(other, VertexProperty) and self.label == other.label and self.value == other.value and self.properties == other.properties

    def __repr__(self):
        return "%s(%r, %r, %r)" % (self.__class__.__name__, self.label, self.value, self.properties)


class Edge(Element):
    """
    Represents an Edge element from a graph query.

    Attributes match initializer parameters.
    """

    element_type = 'edge'

    _attrs = Element._attrs + ('inV', 'inVLabel', 'outV', 'outVLabel')

    def __init__(self, id, label, type, properties,
                 inV, inVLabel, outV, outVLabel):
        super(Edge, self).__init__(id, label, type, properties)
        self.inV = inV
        self.inVLabel = inVLabel
        self.outV = outV
        self.outVLabel = outVLabel

    def __repr__(self):
        return "%s(%r, %r, %r, %r, %r, %r, %r, %r)" %\
               (self.__class__.__name__,
                self.id, self.label,
                self.type, self.properties,
                self.inV, self.inVLabel,
                self.outV, self.outVLabel)


class Path(object):
    """
    Represents a graph path.

    Labels list is taken verbatim from the results.

    Objects are either :class:`~.Result` or :class:`~.Vertex`/:class:`~.Edge` for recognized types
    """

    labels = None
    """
    List of labels in the path
    """

    objects = None
    """
    List of objects in the path
    """

    def __init__(self, labels, objects):
        # The Path class should not do any deserialization by itself. To fix in the next major.
        from dse.graph.query import  _graph_object_sequence
        self.labels = labels
        self.objects = list(_graph_object_sequence(objects))

    def __eq__(self, other):
        return self.labels == other.labels and self.objects == other.objects

    def __str__(self):
        return str({'labels': self.labels, 'objects': self.objects})

    def __repr__(self):
        return "%s(%r, %r)" % (self.__class__.__name__, self.labels, [o.value for o in self.objects])
