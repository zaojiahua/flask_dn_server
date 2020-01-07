import sys

from dn.common.local import LocalProxy, LocalStack
from dn.common.memoize import MemoizeMetaclass


class _AppCtxGlobals(object):
    """A plain object."""

    def get(self, name, default=None):
        return self.__dict__.get(name, default)

    def __contains__(self, item):
        return item in self.__dict__

    def __iter__(self):
        return iter(self.__dict__)

    def __repr__(self):
        return '<rock_g of %r>' % object.__repr__(self)


_app_ctx_stack = LocalStack()


class RockContext(object):
    """The application context binds an application object implicitly
    to the current thread or greenlet, similar to how the
    :class:`RequestContext` binds request information.  The application
    context is also implicitly created if a request context is created
    but the application is not on top of the individual application
    context.
    """

    def __init__(self, **kwargs):
        self.g = _AppCtxGlobals()
        for k, v in kwargs.items():
            setattr(self.g, k, v)

        # Like request context, app contexts can be pushed multiple times
        # but there a basic "refcount" is enough to track them.
        self._refcnt = 0

    def push(self):
        """Binds the app context to the current context."""
        self._refcnt += 1
        if hasattr(sys, 'exc_clear'):
            sys.exc_clear()
        _app_ctx_stack.push(self)

    def pop(self, exc=None):
        """Pops the app context."""
        self._refcnt -= 1
        if self._refcnt <= 0:
            pass
        rv = _app_ctx_stack.pop()
        assert rv is self, 'Popped wrong app context.  (%r instead of %r)' \
            % (rv, self)

    def __enter__(self):
        self.push()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.pop(exc_value)


_app_ctx_err_msg = '''\
Working outside of rock context.

To solve this set up an context with RockContext().\
'''


def _lookup_app_object():
    top = _app_ctx_stack.top
    if top is None:
        raise RuntimeError(_app_ctx_err_msg)
    return getattr(top, 'g')


rock_g = LocalProxy(_lookup_app_object)


class RockNamespace(object):
    __metaclass__ = MemoizeMetaclass

    def __init__(self, name):
        self.name = name

    def get(self, name, default=None):
        return self.__dict__.get(name, default)

    def __contains__(self, item):
        return item in self.__dict__

    def __iter__(self):
        return iter(self.__dict__)

    def __repr__(self):
        return '<RockNamespace of %r>' % self.name


class ObjectWrapper(object):
    def __init__(self):
        self.target = None

    def set_target_object(self, target):
        if target is not None and self.target is None:
            self.target = target

    def __call__(self):
        def _lookup():
            rv = self.target
            return rv
        return LocalProxy(_lookup)


statsd_object = ObjectWrapper()
statsd = statsd_object()

config_object = ObjectWrapper()
config = config_object()
