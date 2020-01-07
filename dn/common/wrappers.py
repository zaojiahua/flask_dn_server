from urllib.parse import parse_qs, urlparse

from redis import Redis

from dn.common import log
from dn.common.memoize import MemoizeMetaclass

logger = log.get_logger('common.wrappers')


class RedisClient(Redis):
    __metaclass__ = MemoizeMetaclass

    @classmethod
    def create(cls, config, **kwargs):
        """
        Constructor for non-factory Flask applications
        """
        def build_redis_config(url):
            parsed = urlparse(url)
            config = dict(host=parsed.hostname,
                          port=parsed.port,
                          db=int(parsed.path[1:].strip() or '0'))
            params = parse_qs(parsed.query)
            for k, v in params.items():
                if k in ['host', 'port', 'db']:
                    continue
                config[k] = v[0]
            return config

        if not isinstance(config, dict):
            config = build_redis_config(config)
        for k in ['host', 'port', 'db']:
            kwargs.pop(k, None)
        config.update(kwargs)
        return cls(**config)


class RedisStore(RedisClient):
    pass


class RedisScript(object):
    _functions = {
        'hgetall': """
            function (key)
                local bulk = redis.call('HGETALL', key)
                local result = {}
                local nextkey
                for i, v in ipairs(bulk) do
                    if i % 2 == 1 then
                        nextkey = v
                    else
                        result[nextkey] = v
                    end
                end
                return result
            end
        """,
        'hmget': """
            function (key, ...)
                if next(arg) == nil then return {} end
                local bulk = redis.call('HMGET', key, unpack(arg))
                local result = {}
                for i, v in ipairs(bulk) do
                    if v then
                        result[ arg[i] ] = v
                    end
                end
                return result
            end
        """,
        'hmset': """
            function (key, dict)
              if next(dict) == nil then return nil end
                local bulk = {}
                for k, v in pairs(dict) do
                    table.insert(bulk, k)
                    table.insert(bulk, v)
                end
                return redis.call('HMSET', key, unpack(bulk))
            end
        """,
        'dict2bulk': """
            function (dict)
              local result = {}
                for k, v in pairs(dict) do
                    table.insert(result, k)
                    table.insert(result, v)
                end
                return result
            end
        """,
        'bulk2dict': """
            function (bulk)
                local result = {}
                for i, v in ipairs(bulk) do
                    if i % 2 == 1 then
                        nextkey = v
                    else
                        result[nextkey] = v
                    end
                end
                return result
            end
        """
    }

    def __init__(self, name, script, using='', return_dict=False, client=None):
        self.client = client
        self.name = name
        self.raw_script = script
        self.using = using.split(' ')
        self.script = self.normalize_script(self.raw_script)
        self.return_dict = return_dict
        self._registered_scripts = {}

    def normalize_script(self, raw_script):
        s = []
        appened = set()
        for func in self.using:
            if not func:
                continue
            if func in appened:
                continue
            else:
                appened.add(func)
            t = self._functions.get(func)
            if not t:
                logger.error('func: %s not valid' % (func))
                continue
            s.append('local %s = %s' % (func, t.strip(' \t\r\n')))
        s.append(raw_script.strip('\r\n'))
        return '\n'.join(s)

    def registered_script(self, client):
        if client not in self._registered_scripts:
            self._registered_scripts[client] \
                = client.register_script(self.script)
        return self._registered_scripts[client]

    def __call__(self, keys=[], args=[], client=None):
        if client is None:
            client = self.client
        if client is None:
            raise RuntimeError(
                'redis client should be set when RedisScript init or called.')
        script = self.registered_script(client)
        ret = None
        try:
            ret = script(keys, args, client=client)
        except Exception as e:
            logger.error(
                'redis script %s error, message:%s' % (self.name, str(e)))

        if self.return_dict:
            if not isinstance(ret, (list, tuple)):
                raise RuntimeError(
                    'script %s must return bulk value' % self.name)
            it = iter(ret)
            return dict(zip(it, it))
        else:
            return ret
