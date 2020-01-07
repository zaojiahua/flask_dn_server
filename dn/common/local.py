"""
    werkzeug.local
    ~~~~~~~~~~~~~~

    This module implements context-local objects.

    :copyright: (c) 2014 by the Werkzeug Team, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""
import copy
from functools import update_wrapper

from werkzeug._compat import PY2, implements_bool
from werkzeug.wsgi import ClosingIterator

# since each thread has its own greenlet we can just use those as identifiers
# for the context.  If greenlets are not available we fall back to the
# current thread ident depending on where it is.
try:
    from greenlet import getcurrent as get_ident
except ImportError:
    try:
        from thread import get_ident
    except ImportError:
        from _thread import get_ident


def cmp(a, b):
    return (a > b) - (a < b)


def release_local(local):
    """Releases the contents of the local for the current context.
    This makes it possible to use locals without a manager.

    Example::

        >>> loc = Local()
        >>> loc.foo = 42
        >>> release_local(loc)
        >>> hasattr(loc, 'foo')
        False

    With this function one can release :class:`Local` objects as well
    as :class:`LocalStack` objects.  However it is not possible to
    release data held by proxies that way, one always has to retain
    a reference to the underlying local object in order to be able
    to release it.

    .. versionadded:: 0.6.1
    """
    local.__release_local__()


class Local(object):
    __slots__ = ('__storage__', '__ident_func__')

    def __init__(self):
        object.__setattr__(self, '__storage__', {})
        object.__setattr__(self, '__ident_func__', get_ident)

    def __iter__(self):
        return iter(self.__storage__.items())

    def __call__(self, proxy):
        """Create a proxy for a name."""
        return LocalProxy(self, proxy)

    def __release_local__(self):
        self.__storage__.pop(self.__ident_func__(), None)

    def __getattr__(self, name):
        try:
            return self.__storage__[self.__ident_func__()][name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        ident = self.__ident_func__()
        storage = self.__storage__
        try:
            storage[ident][name] = value
        except KeyError:
            storage[ident] = {name: value}

    def __delattr__(self, name):
        try:
            del self.__storage__[self.__ident_func__()][name]
        except KeyError:
            raise AttributeError(name)


class LocalStack(object):

    """This class works similar to a :class:`Local` but keeps a stack
    of objects instead.  This is best explained with an example::

        >>> ls = LocalStack()
        >>> ls.push(42)
        >>> ls.top
        42
        >>> ls.push(23)
        >>> ls.top
        23
        >>> ls.pop()
        23
        >>> ls.top
        42

    They can be force released by using a :class:`LocalManager` or with
    the :func:`release_local` function but the correct way is to pop the
    item from the stack after using.  When the stack is empty it will
    no longer be bound to the current context (and as such released).

    By calling the stack without arguments it returns a proxy that resolves to
    the topmost item on the stack.

    .. versionadded:: 0.6.1
    """

    def __init__(self):
        self._local = Local()

    def __release_local__(self):
        self._local.__release_local__()

    def _get__ident_func__(self):
        return self._local.__ident_func__

    def _set__ident_func__(self, value):
        object.__setattr__(self._local, '__ident_func__', value)
    __ident_func__ = property(_get__ident_func__, _set__ident_func__)
    del _get__ident_func__, _set__ident_func__

    def __call__(self):
        def _lookup():
            rv = self.top
            if rv is None:
                raise RuntimeError('object unbound')
            return rv
        return LocalProxy(_lookup)

    def push(self, obj):
        """Pushes a new item to the stack"""
        rv = getattr(self._local, 'stack', None)
        if rv is None:
            self._local.stack = rv = []
        rv.append(obj)
        return rv

    def pop(self):
        """Removes the topmost item from the stack, will return the
        old value or `None` if the stack was already empty.
        """
        stack = getattr(self._local, 'stack', None)
        if stack is None:
            return None
        elif len(stack) == 1:
            release_local(self._local)
            return stack[-1]
        else:
            return stack.pop()

    @property
    def top(self):
        """The topmost item on the stack.  If the stack is empty,
        `None` is returned.
        """
        try:
            return self._local.stack[-1]
        except (AttributeError, IndexError):
            return None


class LocalManager(object):

    """Local objects cannot manage themselves. For that you need a local
    manager.  You can pass a local manager multiple locals or add them later
    by appending them to `manager.locals`.  Every time the manager cleans up,
    it will clean up all the data left in the locals for this context.

    The `ident_func` parameter can be added to override the default ident
    function for the wrapped locals.

    .. versionchanged:: 0.6.1
       Instead of a manager the :func:`release_local` function can be used
       as well.

    .. versionchanged:: 0.7
       `ident_func` was added.
    """

    def __init__(self, locals=None, ident_func=None):
        if locals is None:
            self.locals = []
        elif isinstance(locals, Local):
            self.locals = [locals]
        else:
            self.locals = list(locals)
        if ident_func is not None:
            self.ident_func = ident_func
            for local in self.locals:
                object.__setattr__(local, '__ident_func__', ident_func)
        else:
            self.ident_func = get_ident

    def get_ident(self):
        """Return the context identifier the local objects use internally for
        this context.  You cannot override this method to change the behavior
        but use it to link other context local objects (such as SQLAlchemy's
        scoped sessions) to the Werkzeug locals.

        .. versionchanged:: 0.7
           You can pass a different ident function to the local manager that
           will then be propagated to all the locals passed to the
           constructor.
        """
        return self.ident_func()

    def cleanup(self):
        """Manually clean up the data in the locals for this context.  Call
        this at the end of the request or use `make_middleware()`.
        """
        for local in self.locals:
            release_local(local)

    def make_middleware(self, app):
        """Wrap a WSGI application so that cleaning up happens after
        request end.
        """
        def application(environ, start_response):
            return ClosingIterator(app(environ, start_response), self.cleanup)
        return application

    def middleware(self, func):
        """Like `make_middleware` but for decorating functions.

        Example usage::

            @manager.middleware
            def application(environ, start_response):
                ...

        The difference to `make_middleware` is that the function passed
        will have all the arguments copied from the inner application
        (name, docstring, module).
        """
        return update_wrapper(self.make_middleware(func), func)

    def __repr__(self):
        return '<%s storages: %d>' % (
            self.__class__.__name__,
            len(self.locals)
        )


@implements_bool
class LocalProxy(object):

    """Acts as a proxy for a werkzeug local.  Forwards all operations to
    a proxied object.  The only operations not supported for forwarding
    are right handed operands and any kind of assignment.

    Example usage::

        from werkzeug.local import Local
        l = Local()

        # these are proxies
        request = l('request')
        user = l('user')


        from werkzeug.local import LocalStack
        _response_local = LocalStack()

        # this is a proxy
        response = _response_local()

    Whenever something is bound to l.user / l.request the proxy objects
    will forward all operations.  If no object is bound a :exc:`RuntimeError`
    will be raised.

    To create proxies to :class:`Local` or :class:`LocalStack` objects,
    call the object as shown above.  If you want to have a proxy to an
    object looked up by a function, you can (as of Werkzeug 0.6.1) pass
    a function to the :class:`LocalProxy` constructor::

        session = LocalProxy(lambda: get_current_request().session)

    .. versionchanged:: 0.6.1
       The class can be instantiated with a callable as well now.
    """
    __slots__ = ('__local', '__dict__', '__name__', '__wrapped__')

    def __init__(self, local, name=None):
        object.__setattr__(self, '_LocalProxy__local', local)
        object.__setattr__(self, '__name__', name)
        if callable(local) and not hasattr(local, '__release_local__'):
            # "local" is a callable that is not an instance of Local or
            # LocalManager: mark it as a wrapped function.
            object.__setattr__(self, '__wrapped__', local)

    def _get_current_object(self):
        """Return the current object.  This is useful if you want the real
        object behind the proxy at a time for performance reasons or because
        you want to pass the object into a different context.
        """
        if not hasattr(self.__local, '__release_local__'):
            return self.__local()
        try:
            return getattr(self.__local, self.__name__)
        except AttributeError:
            raise RuntimeError('no object bound to %s' % self.__name__)

    @property
    def __dict__(self):
        try:
            return self._get_current_object().__dict__
        except RuntimeError:
            raise AttributeError('__dict__')

    def __repr__(self):
        try:
            obj = self._get_current_object()
        except RuntimeError:
            return '<%s unbound>' % self.__class__.__name__
        return repr(obj)

    def __bool__(self):
        try:
            return bool(self._get_current_object())
        except RuntimeError:
            return False

    # python3 unified unicode into str, does this method necessary?
    # change unicode to str, source code reference :
    # https://github.com/pallets/werkzeug/blob/master/werkzeug/local.py
    def __unicode__(self):
        try:
            return str(self._get_current_object())
        except RuntimeError:
            return repr(self)

    def __dir__(self):
        try:
            return dir(self._get_current_object())
        except RuntimeError:
            return []

    def __getattr__(self, name):
        if name == '__members__':
            return dir(self._get_current_object())
        return getattr(self._get_current_object(), name)

    def __setitem__(self, key, value):
        self._get_current_object()[key] = value

    def __delitem__(self, key):
        del self._get_current_object()[key]

    if PY2:
        def __getslice__(x, i, j): return x._get_current_object()[i:j]

        def __setslice__(self, i, j, seq):
            self._get_current_object()[i:j] = seq

        def __delslice__(self, i, j):
            del self._get_current_object()[i:j]

    def __setattr__(x, n, v): return setattr(x._get_current_object(), n, v)

    def __delattr__(x, n): return delattr(x._get_current_object(), n)

    def __str__(x): return str(x._get_current_object())

    def __lt__(x, o): return x._get_current_object() < o

    def __le__(x, o): return x._get_current_object() <= o

    def __eq__(x, o): return x._get_current_object() == o

    def __ne__(x, o): return x._get_current_object() != o

    def __gt__(x, o): return x._get_current_object() > o

    def __ge__(x, o): return x._get_current_object() >= o
    # deprecated cmp in python 3!!!
    # __cmp__ = lambda x, o: cmp(x._get_current_object(), o)
    # __cmp__ = lambda x, o: cmp(x._get_current_object(), o)

    def __hash__(x): return hash(x._get_current_object())
    __call__ = lambda x, *a, **kw: x._get_current_object()(*a, **kw)

    def __len__(x): return len(x._get_current_object())

    def __getitem__(x, i): return x._get_current_object()[i]

    def __iter__(x): return iter(x._get_current_object())

    def __contains__(x, i): return i in x._get_current_object()

    def __add__(x, o): return x._get_current_object() + o

    def __sub__(x, o): return x._get_current_object() - o

    def __mul__(x, o): return x._get_current_object() * o

    def __floordiv__(x, o): return x._get_current_object() // o

    def __mod__(x, o): return x._get_current_object() % o

    def __divmod__(x, o): return x._get_current_object().__divmod__(o)

    def __pow__(x, o): return x._get_current_object() ** o

    def __lshift__(x, o): return x._get_current_object() << o

    def __rshift__(x, o): return x._get_current_object() >> o

    def __and__(x, o): return x._get_current_object() & o

    def __xor__(x, o): return x._get_current_object() ^ o

    def __or__(x, o): return x._get_current_object() | o

    def __div__(x, o): return x._get_current_object().__div__(o)

    def __truediv__(x, o): return x._get_current_object().__truediv__(o)

    def __neg__(x): return -(x._get_current_object())

    def __pos__(x): return +(x._get_current_object())

    def __abs__(x): return abs(x._get_current_object())

    def __invert__(x): return ~(x._get_current_object())

    def __complex__(x): return complex(x._get_current_object())

    def __int__(x): return int(x._get_current_object())
    # deprecated long in python 3
    # __long__ = lambda x: long(x._get_current_object())

    def __long__(x): return int(x._get_current_object())

    def __float__(x): return float(x._get_current_object())

    def __oct__(x): return oct(x._get_current_object())

    def __hex__(x): return hex(x._get_current_object())

    def __index__(x): return x._get_current_object().__index__()

    def __coerce__(x, o): return x._get_current_object().__coerce__(x, o)

    def __enter__(x): return x._get_current_object().__enter__()
    __exit__ = lambda x, *a, **kw: x._get_current_object().__exit__(*a, **kw)

    def __radd__(x, o): return o + x._get_current_object()

    def __rsub__(x, o): return o - x._get_current_object()

    def __rmul__(x, o): return o * x._get_current_object()

    def __rdiv__(x, o): return o / x._get_current_object()
    if PY2:
        def __rtruediv__(x, o): return x._get_current_object().__rtruediv__(o)
    else:
        __rtruediv__ = __rdiv__

    def __rfloordiv__(x, o): return o // x._get_current_object()

    def __rmod__(x, o): return o % x._get_current_object()

    def __rdivmod__(x, o): return x._get_current_object().__rdivmod__(o)

    def __copy__(x): return copy.copy(x._get_current_object())

    def __deepcopy__(x, memo): return copy.deepcopy(
        x._get_current_object(), memo)
