# Copyright DataStax, Inc.
#
# Licensed under the DataStax DSE Driver License;
# you may not use this file except in compliance with the License.
#
# You may obtain a copy of the License at
#
# http://www.datastax.com/terms/datastax-dse-driver-license-terms
"""
Module that implements an event loop based on twisted
( https://twistedmatrix.com ).
"""
import atexit
from functools import partial
import logging
from threading import Thread, Lock
import time
from twisted.internet import reactor, protocol
import weakref

from dse.connection import Connection, ConnectionShutdown, Timer, TimerManager


log = logging.getLogger(__name__)


def _cleanup(cleanup_weakref):
    try:
        cleanup_weakref()._cleanup()
    except ReferenceError:
        return


class TwistedConnectionProtocol(protocol.Protocol):
    """
    Twisted Protocol class for handling data received and connection
    made events.
    """

    def __init__(self):
        self.connection = None

    def dataReceived(self, data):
        """
        Callback function that is called when data has been received
        on the connection.

        Reaches back to the Connection object and queues the data for
        processing.
        """
        self.connection._iobuf.write(data)
        self.connection.handle_read()
    def connectionMade(self):
        """
        Callback function that is called when a connection has succeeded.

        Reaches back to the Connection object and confirms that the connection
        is ready.
        """
        try:
            # Non SSL connection
            self.connection = self.transport.connector.factory.conn
        except AttributeError:
            # SSL connection
            self.connection = self.transport.connector.factory.wrappedFactory.conn

        self.connection.client_connection_made(self.transport)

    def connectionLost(self, reason):
        # reason is a Failure instance
        self.connection.defunct(reason.value)


class TwistedConnectionClientFactory(protocol.ClientFactory):

    def __init__(self, connection):
        # ClientFactory does not define __init__() in parent classes
        # and does not inherit from object.
        self.conn = connection

    def buildProtocol(self, addr):
        """
        Twisted function that defines which kind of protocol to use
        in the ClientFactory.
        """
        return TwistedConnectionProtocol()

    def clientConnectionFailed(self, connector, reason):
        """
        Overridden twisted callback which is called when the
        connection attempt fails.
        """
        log.debug("Connect failed: %s", reason)
        self.conn.defunct(reason.value)

    def clientConnectionLost(self, connector, reason):
        """
        Overridden twisted callback which is called when the
        connection goes away (cleanly or otherwise).

        It should be safe to call defunct() here instead of just close, because
        we can assume that if the connection was closed cleanly, there are no
        requests to error out. If this assumption turns out to be false, we
        can call close() instead of defunct() when "reason" is an appropriate
        type.
        """
        log.debug("Connect lost: %s", reason)
        self.conn.defunct(reason.value)


class TwistedLoop(object):

    _lock = None
    _thread = None
    _timeout_task = None
    _timeout = None

    def __init__(self):
        self._lock = Lock()
        self._timers = TimerManager()

    def maybe_start(self):
        with self._lock:
            if not reactor.running:
                self._thread = Thread(target=reactor.run,
                                      name="dse_driver_twisted_event_loop",
                                      kwargs={'installSignalHandlers': False})
                self._thread.daemon = True
                self._thread.start()
                atexit.register(partial(_cleanup, weakref.ref(self)))

    def _cleanup(self):
        if self._thread:
            reactor.callFromThread(reactor.stop)
            self._thread.join(timeout=1.0)
            if self._thread.is_alive():
                log.warning("Event loop thread could not be joined, so "
                            "shutdown may not be clean. Please call "
                            "Cluster.shutdown() to avoid this.")
            log.debug("Event loop thread was joined")

    def add_timer(self, timer):
        self._timers.add_timer(timer)
        # callFromThread to schedule from the loop thread, where
        # the timeout task can safely be modified
        reactor.callFromThread(self._schedule_timeout, timer.end)

    def _schedule_timeout(self, next_timeout):
        if next_timeout:
            delay = max(next_timeout - time.time(), 0)
            if self._timeout_task and self._timeout_task.active():
                if next_timeout < self._timeout:
                    self._timeout_task.reset(delay)
                    self._timeout = next_timeout
            else:
                self._timeout_task = reactor.callLater(delay, self._on_loop_timer)
                self._timeout = next_timeout

    def _on_loop_timer(self):
        self._timers.service_timeouts()
        self._schedule_timeout(self._timers.next_timeout)


try:
    from twisted.internet import ssl
    import OpenSSL.crypto
    from OpenSSL.crypto import load_certificate, FILETYPE_PEM

    class _SSLContextFactory(ssl.ClientContextFactory):
        def __init__(self, ssl_options, check_hostname, host):
            self.ssl_options = ssl_options
            self.check_hostname = check_hostname
            self.host = host

        def getContext(self):
            # This version has to be OpenSSL.SSL.DESIRED_VERSION
            # instead of ssl.DESIRED_VERSION as in other loops
            self.method = self.ssl_options["ssl_version"]
            context = ssl.ClientContextFactory.getContext(self)
            if "certfile" in self.ssl_options:
                context.use_certificate_file(self.ssl_options["certfile"])
            if "keyfile" in self.ssl_options:
                context.use_privatekey_file(self.ssl_options["keyfile"])
            if "ca_certs" in self.ssl_options:
                x509 = load_certificate(FILETYPE_PEM, open(self.ssl_options["ca_certs"]).read())
                store = context.get_cert_store()
                store.add_cert(x509)
            if "cert_reqs" in self.ssl_options:
                # This expects OpenSSL.SSL.VERIFY_NONE/OpenSSL.SSL.VERIFY_PEER
                # or OpenSSL.SSL.VERIFY_FAIL_IF_NO_PEER_CERT
                context.set_verify(self.ssl_options["cert_reqs"],
                                   callback=self.verify_callback)
            return context

        def verify_callback(self, connection, x509, errnum, errdepth, ok):
            if ok:
                if self.check_hostname and self.host != x509.get_subject().commonName:
                    return False
            return ok

    _HAS_SSL = True

except ImportError as e:
    _HAS_SSL = False


class TwistedConnection(Connection):
    """
    An implementation of :class:`.Connection` that utilizes the
    Twisted event loop.
    """

    _loop = None

    @classmethod
    def initialize_reactor(cls):
        if not cls._loop:
            cls._loop = TwistedLoop()

    @classmethod
    def create_timer(cls, timeout, callback):
        timer = Timer(timeout, callback)
        cls._loop.add_timer(timer)
        return timer

    def __init__(self, *args, **kwargs):
        """
        Initialization method.

        Note that we can't call reactor methods directly here because
        it's not thread-safe, so we schedule the reactor/connection
        stuff to be run from the event loop thread when it gets the
        chance.
        """
        Connection.__init__(self, *args, **kwargs)

        self.is_closed = True
        self.connector = None
        self.transport = None

        reactor.callFromThread(self.add_connection)
        self._loop.maybe_start()

    def add_connection(self):
        """
        Convenience function to connect and store the resulting
        connector.
        """
        if self.ssl_options:

            if not _HAS_SSL:
                raise ImportError(
                    str(e) +
                    ', pyOpenSSL must be installed to enable SSL support with the Twisted event loop'
                )

            self.connector = reactor.connectSSL(
                host=self.endpoint.address, port=self.port,
                factory=TwistedConnectionClientFactory(self),
                contextFactory=_SSLContextFactory(self.ssl_options, self._check_hostname, self.endpoint.address),
                timeout=self.connect_timeout)
        else:
            self.connector = reactor.connectTCP(
                host=self.endpoint.address, port=self.port,
                factory=TwistedConnectionClientFactory(self),
                timeout=self.connect_timeout)

    def client_connection_made(self, transport):
        """
        Called by twisted protocol when a connection attempt has
        succeeded.
        """
        with self.lock:
            self.is_closed = False
        self.transport = transport
        self._send_options_message()

    def close(self):
        """
        Disconnect and error-out all requests.
        """
        with self.lock:
            if self.is_closed:
                return
            self.is_closed = True

        log.debug("Closing connection (%s) to %s", id(self), self.endpoint)
        reactor.callFromThread(self.connector.disconnect)
        log.debug("Closed socket to %s", self.endpoint)

        if not self.is_defunct:
            self.error_all_requests(
                ConnectionShutdown("Connection to %s was closed" % self.endpoint))
            # don't leave in-progress operations hanging
            self.connected_event.set()

    def handle_read(self):
        """
        Process the incoming data buffer.
        """
        self.process_io_buffer()

    def push(self, data):
        """
        This function is called when outgoing data should be queued
        for sending.

        Note that we can't call transport.write() directly because
        it is not thread-safe, so we schedule it to run from within
        the event loop when it gets the chance.
        """
        reactor.callFromThread(self.transport.write, data)
