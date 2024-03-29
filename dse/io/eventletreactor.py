# Copyright DataStax, Inc.
#
# Licensed under the DataStax DSE Driver License;
# you may not use this file except in compliance with the License.
#
# You may obtain a copy of the License at
#
# http://www.datastax.com/terms/datastax-dse-driver-license-terms

# Originally derived from MagnetoDB source:
#   https://github.com/stackforge/magnetodb/blob/2015.1.0b1/magnetodb/common/cassandra/io/eventletreactor.py

import eventlet
from eventlet.green import socket
from eventlet.queue import Queue
from greenlet import GreenletExit
import logging
from threading import Event
import time

from six.moves import xrange

from dse.connection import Connection, ConnectionShutdown, Timer, TimerManager


log = logging.getLogger(__name__)


class EventletConnection(Connection):
    """
    An implementation of :class:`.Connection` that utilizes ``eventlet``.

    This implementation assumes all eventlet monkey patching is active. It is not tested with partial patching.
    """

    _read_watcher = None
    _write_watcher = None

    _socket_impl = eventlet.green.socket
    _ssl_impl = eventlet.green.ssl

    _timers = None
    _timeout_watcher = None
    _new_timer = None

    @classmethod
    def initialize_reactor(cls):
        eventlet.monkey_patch()
        if not cls._timers:
            cls._timers = TimerManager()
            cls._timeout_watcher = eventlet.spawn(cls.service_timeouts)
            cls._new_timer = Event()

    @classmethod
    def create_timer(cls, timeout, callback):
        timer = Timer(timeout, callback)
        cls._timers.add_timer(timer)
        cls._new_timer.set()
        return timer

    @classmethod
    def service_timeouts(cls):
        """
        cls._timeout_watcher runs in this loop forever.
        It is usually waiting for the next timeout on the cls._new_timer Event.
        When new timers are added, that event is set so that the watcher can
        wake up and possibly set an earlier timeout.
        """
        timer_manager = cls._timers
        while True:
            next_end = timer_manager.service_timeouts()
            sleep_time = max(next_end - time.time(), 0) if next_end else 10000
            cls._new_timer.wait(sleep_time)
            cls._new_timer.clear()

    def __init__(self, *args, **kwargs):
        Connection.__init__(self, *args, **kwargs)
        self._write_queue = Queue()

        self._connect_socket()

        self._read_watcher = eventlet.spawn(lambda: self.handle_read())
        self._write_watcher = eventlet.spawn(lambda: self.handle_write())
        self._send_options_message()

    def close(self):
        with self.lock:
            if self.is_closed:
                return
            self.is_closed = True

        log.debug("Closing connection (%s) to %s" % (id(self), self.endpoint))

        cur_gthread = eventlet.getcurrent()

        if self._read_watcher and self._read_watcher != cur_gthread:
            self._read_watcher.kill()
        if self._write_watcher and self._write_watcher != cur_gthread:
            self._write_watcher.kill()
        if self._socket:
            self._socket.close()
        log.debug("Closed socket to %s" % (self.endpoint,))

        if not self.is_defunct:
            self.error_all_requests(
                ConnectionShutdown("Connection to %s was closed" % self.endpoint))
            # don't leave in-progress operations hanging
            self.connected_event.set()

    def handle_close(self):
        log.debug("connection closed by server")
        self.close()

    def handle_write(self):
        while True:
            try:
                next_msg = self._write_queue.get()
                self._socket.sendall(next_msg)
            except socket.error as err:
                log.debug("Exception during socket send for %s: %s", self, err)
                self.defunct(err)
                return  # Leave the write loop
            except GreenletExit:  # graceful greenthread exit
                return

    def handle_read(self):
        while True:
            try:
                buf = self._socket.recv(self.in_buffer_size)
                self._iobuf.write(buf)
            except socket.error as err:
                log.debug("Exception during socket recv for %s: %s",
                          self, err)
                self.defunct(err)
                return  # leave the read loop
            except GreenletExit:  # graceful greenthread exit
                return

            if buf and self._iobuf.tell():
                self.process_io_buffer()
            else:
                log.debug("Connection %s closed by server", self)
                self.close()
                return

    def push(self, data):
        chunk_size = self.out_buffer_size
        for i in xrange(0, len(data), chunk_size):
            self._write_queue.put(data[i:i + chunk_size])
