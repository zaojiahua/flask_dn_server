import logging
import platform
import traceback
from logging import NullHandler, StreamHandler
from logging import getLogger as _getLogger
from logging.handlers import SysLogHandler

from dn.common import lln


root_logger = None
null_logger = None
logger_cache = {}
logger_filters = {}
_stdout = True
_root_logger_name = 'noapp'
_disabled_logger = []


def get_logger(name=''):
    global logger_cache
    if name not in logger_cache:
        logger_cache[name] = LoggerProxy(name)
    return logger_cache[name]


def setup(root='noapp', stdout=True, filters={}):
    global _stdout, _root_logger_name
    _stdout = stdout
    _root_logger_name = root
    add_filters(filters)


def add_filters(filters={}):
    for k, v in filters.items():
        if k[0] == '.':
            k = '%s%s' % (_root_logger_name, k)
        logger_filters[k] = v
        if v.upper() == 'OFF':
            _disabled_logger.append(k)


def syslog_handlers(
        logger_name, address=('127.0.0.1', 514), facility=0, level='DEBUG'):
    global _root_logger_name, root_logger, _stdout
    logger_names = []
    loggers = []
    if type(logger_name) in [str]:
        logger_names = [logger_name]
    elif type(logger_name) in [list, tuple]:
        logger_names = logger_name
    else:
        return loggers
    for name in logger_names:
        logger = _getLogger(name)
        _level = logger_filters.get(name) or level
        _level = _level.upper()
        if _level == 'OFF':
            handler = NullHandler()
            logger.addHandler(handler)
        elif _level in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
            del logger.handlers[:]
            logger.setLevel(_level)
            handler = SysLogHandler(
                address=tuple(address),
                facility=SysLogHandler.LOG_LOCAL0 + facility
            )
            handler.setLevel(_level)
            logger.addHandler(handler)
            if _stdout:
                handler = StdoutHandler()
                handler.setLevel(_level)
                logger.addHandler(handler)
        logger.propagate = 0
        if name == _root_logger_name:
            root_logger = logger
        loggers.append(logger)
    return loggers


class StdoutHandler(StreamHandler):
    def emit(self, record):
        global _stdout
        StreamHandler.emit(self, record) if _stdout else None


class LoggerProxy(object):
    def __init__(self, name):
        self.name = name
        self._logger = None

    @property
    def root_logger(self):
        global root_logger
        if root_logger is None:
            root_logger = syslog_handlers(_root_logger_name)[0]
        return root_logger

    @property
    def null_logger(self):
        global null_logger
        if null_logger is None:
            null_logger = syslog_handlers('null_logger', level='OFF')[0]
        return null_logger

    @property
    def logger(self):
        if self._logger is None:
            if self.name:
                full_name = '%s.%s' % (_root_logger_name, self.name)
                for disabled in _disabled_logger:
                    if full_name.startswith(disabled):
                        self._logger = self.null_logger
                if self._logger is None:
                    self._logger = self.root_logger.getChild(self.name)

                level = logger_filters.get(full_name)
                if level and level.upper() \
                        in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
                    self._logger.setLevel(level.upper())
            else:
                self._logger = self.root_logger
        return self._logger

    def __getattr__(self, attrib):
        return getattr(self.logger, attrib)


class LLNLogger(logging.getLoggerClass()):
    log_formatter = logging.Formatter(
        '%(asctime)s.%(msecs)03d|' +
        platform.node().split('.')[0] +
        '|%(levelname)s|%(name)s|%(message)s',
        '%Y-%m-%dT%H:%M:%S')

    __client = None

    def __init__(self, name, level=logging.NOTSET):
        super(LLNLogger, self).__init__(name, level)

    def _get_client(self):
        return self.__client

    def captureException(self, exc_info=None, **kwargs):
        client = self._get_client()
        msg = client.buildException(
            exc_info=exc_info, **kwargs
        ) if client else None
        if msg:
            self.error('SENTRY', msg)
        # client.captureException()

    def captureMessage(self, message, **kwargs):
        client = self._get_client()
        msg = client.buildMessage(message, **kwargs) if client else None
        if msg:
            self.error('SENTRY', msg)
        # client.captureMessage(message)

    def addHandler(self, handler):
        handler.setFormatter(self.__class__.log_formatter)
        super(LLNLogger, self).addHandler(handler)

    def makeRecord(
            self, name, level, fn, lno, msg, args,
            exc_info, func=None, extra=None, sinfo=None
    ):
        if not isinstance(msg, str):
            msg = str(msg)
        if '%s' not in msg:
            if isinstance(msg, str) and msg.lower() == 'traceback':
                lst = ['TRACEBACK|']
                lst.extend(args)
                msg = '\n'.join(lst).replace('\n', '\n##')
                args = None
            else:
                msgs = [msg]
                msgs.extend(args)
                msg = lln.dumps(msgs)
                args = None

            if isinstance(msg, bytes):
                msg = self.str_decode(msg)

        return super(LLNLogger, self).makeRecord(
            name, level, fn, lno, msg, args, exc_info, func, extra, sinfo)

    def traceback(self):
        self.error('TRACEBACK', traceback.format_exc())

    def str_decode(self, string, encoding='utf-8'):
        return string.decode(encoding)


logging.setLoggerClass(LLNLogger)
