import operator
import os
import shutil
import time
from functools import reduce

from dn.common import log
from dn.common.wrappers import RedisStore

import yaml


logger = log.get_logger('config')


def get_target_path(path, matrix):
    try:
        # print('-------------------')
        # print(path)
        # print(matrix)
        return reduce(operator.getitem, path, matrix)
    except KeyError:
        logger.error('ALERT', 'autoload_resource_import_failed',
                     ('path', '.'.join(path)))
        return None


class ReadOnlyDict(dict):

    __readonly = False

    def readonly(self, allow=1):
        """Allow or deny modifying dictionary"""
        self.__readonly = bool(allow)

    def __setitem__(self, key, value):

        if self.__readonly:
            raise TypeError("__setitem__ is not supported")
        return dict.__setitem__(self, key, value)

    def __delitem__(self, key):

        if self.__readonly:
            raise TypeError("__delitem__ is not supported")
        return dict.__delitem__(self, key)


class RemoteSettingsDict(dict):
    def __init__(self, remote_config, **kwargs):
        super(RemoteSettingsDict, self).__init__(**kwargs)
        self.update(remote_config)

    def get_value(self, name):
        name_list = name.split("/")
        data = self.resource
        for name_ in name_list:
            assert name_ in data, "remote setting error for rs:///%s" % name
            data = data.get(name_)
        return data

    @property
    def resource(self):
        return self.get("resource", {})

    @property
    def values(self):
        data = self.copy()
        if "resource" in data:
            data.pop("resource")
        return data


class LeftJoinDict(dict):

    def __init__(self, config, **kwargs):
        super(LeftJoinDict, self).__init__(**kwargs)
        self.update(config)

    @staticmethod
    def join_left(left_value, right_value):
        if isinstance(right_value, dict):
            for k, v in right_value.items():
                if k not in left_value or \
                        not isinstance(left_value.get(k), dict):
                    left_value[k] = v
                else:
                    left_value[k] = LeftJoinDict.join_left(
                        left_value.get(k), v)
        return left_value

    def __add__(self, right_value):
        assert isinstance(right_value, dict), "right_value is not a dict"
        return LeftJoinDict.join_left(self.copy(), right_value)


autoload_nodes = []
loadonce_nodes = []
remote_settings = None


class AutoloadResource(object):
    autoload_resources = {}

    @classmethod
    def create(cls, **kwargs):
        reskey = '%s://%s' % (kwargs['location'], kwargs['name'])
        if reskey not in cls.autoload_resources:
            cls.autoload_resources[reskey] = AutoloadResource(**kwargs)

        ret = cls.autoload_resources[reskey]
        ret.set_interval(kwargs['check_interval'])
        return ret

    def __init__(self, name, location='local',
                 check_interval=600, preprocessor=None, **kwargs):
        self.name = name
        self.location = location
        self.check_interval = check_interval
        self.preprocessor = None
        self._data = None
        self._last_checked = 0
        self.remote_config = {}
        self.ssm_config = {}

    def to_dict(self):
        return {'name': self.name, 'location': self.location}

    def set_remote(self, remote_config):
        self.remote_config = remote_config

    def set_ssm(self, ssm_config):
        self.ssm_config = ssm_config

    def set_interval(self, interval):
        if interval < self.check_interval:
            self.check_interval = interval

    def register_preprocessor(self, preprocessor):
        if not callable(preprocessor):
            logger.error(
                'ALERT', 'autoload_resource_register_failed',
                'preprocessor is not callable', preprocessor)
            return
        self.preprocessor = preprocessor
        self.load()

    def get(self):
        checked = int(time.time() / self.check_interval)
        if checked > self._last_checked or self.location == "rs":
            self._last_checked = checked
            try:
                self.load()
            except Exception as ex:
                import sys
                import traceback
                logger.error('EXCEPTION', sys.exc_info()[1])
                logger.error("EXCEPTION_INFO", str(ex))
                logger.error('TRACEBACK', traceback.format_exc())
                logger.error(
                    'ALERT', 'autoload_resource_load_failed',
                    self.to_dict())
                logger.captureException()

        return self._data

    def load(self):
        logger.debug('autolaod_resource_load', self.to_dict())

        data = None
        if self.location == 'local':
            with open('data/%s' % self.name, 'rb') as f:
                data = f.read()
        elif self.location == 's3':
            data = self.load_s3_resource()
        elif self.location == 'ssm':
            data = self.load_ssm_value()
        elif self.location == 'rs':
            data = self.load_rs_value()

        if self.name[-5:] == '.yaml' and data:
            data = yaml.load(data)

        if self.preprocessor:
            logger.debug(
                'autoload_resources load data with preprocessor',
                'orgin_data', data)
            data = self.preprocessor(data)
            logger.debug(
                'autoload_resources load data with preprocessor',
                self.preprocessor, data)

        self._data = data

    def load_s3_resource(self):
        import boto.s3.connection
        remote_config = self.remote_config
        bucket_name = remote_config.get('bucket')
        region = remote_config.get('region')
        folder = remote_config.get('folder')
        key_name = '%s/%s' % (folder, self.name) if folder else self.name
        if bucket_name.lower() != bucket_name:
            calling_format = boto.s3.connection.OrdinaryCallingFormat()
        else:
            calling_format = boto.s3.connection.SubdomainCallingFormat()
        kwargs = {'aws_access_key_id':
                  remote_config.get('aws_access_key_id'),
                  'aws_secret_access_key':
                  remote_config.get('aws_secret_access_key'),
                  'calling_format': calling_format}
        conn = boto.s3.connect_to_region(region, **kwargs)
        bucket = conn.get_bucket(bucket_name, validate=False)
        key = bucket.get_key(key_name, validate=False)
        return key.get_contents_as_string()

    def load_ssm_value(self):
        """
        load value from aws ssm parameter store
        :return: value of ssm param
        """
        import boto3
        from botocore.client import Config

        ssm_config = self.ssm_config
        kwargs = {'aws_access_key_id':
                  ssm_config.get('aws_access_key_id').get(),
                  'aws_secret_access_key':
                  ssm_config.get('aws_secret_access_key').get(),
                  'region_name': ssm_config.get('region'),
                  'config': Config(
                      connect_timeout=300, read_timeout=300,
                      retries={'max_attempts': 6})}

        ssm = boto3.client('ssm', **kwargs)
        resp = ssm.get_parameter(Name=self.name, WithDecryption=True)

        return resp.get('Parameter', {}).get('Value')

    def load_rs_value(self):
        if not remote_settings:
            return None
        assert isinstance(
            remote_settings, RemoteSettingsDict), \
            "can't use remote settings"
        data = remote_settings.get_value(self.name[1:])
        return data


class ImportCommand(object):
    load_once = False

    def __init__(self, key=None, **kwargs):
        self.key = key.split('.') if key else []
        self.preload = kwargs.get('preload', True)
        self.load_once = kwargs.get('load_once', False)

        self.resource = AutoloadResource.create(**kwargs)

    def get(self):
        data = self.resource.get()
        if self.key:
            return get_target_path(self.key, data)
        return data

    def set_remote(self, remote_config):
        self.resource.set_remote(remote_config)

    def set_ssm(self, remote_config):
        self.resource.set_ssm(remote_config)

    def load(self):
        self.resource.load()

    def __getattr__(self, item):
        if not self.load_once:
            # super(ImportCommand, self).__getattr__(item)
            super(ImportCommand, self).__getattribute__(item)
        else:
            return self.get()


def import_yaml(loader, node):
    """Include another YAML file or Other Resource File."""

    statement = loader.construct_scalar(node)
    tokens = statement.split(' ')
    tokens = [token for token in filter(lambda x: len(x.strip()) > 0, tokens)]
    args = {'preload': True, 'check_interval': 600}
    # extra = []
    if 'from' not in tokens:
        args['location'], args['name'] = tokens[0].split('://')
        extra = tokens[1:]
    elif tokens[1] == 'from':
        args['key'] = tokens[0]
        args['location'], args['name'] = tokens[2].split('://')
        extra = tokens[3:]
    else:
        raise RuntimeError('wrong !import command: %s.' % statement)

    for token in extra:
        if '=' in token:
            k, v = token.split('=')
            if not k or not v:
                raise RuntimeError('wrong !import command args: %s.' % token)
            if k == 'interval':
                args['check_interval'] = int(v)
            else:
                raise RuntimeError('unknown !import command args: %s.' % token)
        else:
            if token == 'lazy_load':
                args['preload'] = False
            elif token == 'load_once':
                args['load_once'] = True
            else:
                raise RuntimeError('unknown !import command args: %s.' % token)
    node = ImportCommand(**args)
    autoload_nodes.append(node)
    if node.load_once:
        loadonce_nodes.append(node)
    return node


"""
    foo: !import auth.foo from local://aaa.yaml lazy_load interval=600
    foo: !import s3://aaa.yaml lazy_load interval=600
"""

yaml.add_constructor('!import', import_yaml)


def load_once(config):
    if isinstance(config, dict):
        for k, v in config.items():
            config[k] = load_once(v)
    elif isinstance(config, ImportCommand):
        if config in loadonce_nodes:
            config = config.get()
    return config


class YamlConfig(ReadOnlyDict):
    def __init__(self, config_file=None, **kwargs):
        super(YamlConfig, self).__init__(**kwargs)
        if not config_file:
            return
        self._create_config_from_template(config_file)
        with open(config_file, encoding='UTF-8') as f:
            c = yaml.load(f)
            self.update(c)
        self._redis_instances = None

    def preload(self):
        global remote_settings
        for node in autoload_nodes:
            node.set_remote(self.get('main', {}).get('remote_resource', {}))
            node.set_ssm(self.get('main', {}).get('ssm', {}))
            if node.preload:
                node.get()

        for remote_config_key in self.remote_list:

            config_string = self.get(remote_config_key, {}).\
                get("remote_setting", {}).get().strip()

            logger.debug("Get Remote Info", config_string)

            remote_config = None
            try:
                remote_config = yaml.load(config_string)
                assert not isinstance(remote_config, str)
            except Exception as e:
                import traceback
                logger.error("EXCEPTION", e)
                logger.error('TRACEBACK', traceback.format_exc())
                logger.error('ALERT', 'remote config load failed')
                logger.captureException()

            remote_settings = RemoteSettingsDict(remote_config or {})
            lj_remote_config = LeftJoinDict(remote_settings.values)
            lj_self = LeftJoinDict(self.get(remote_config_key, {}))
            self.get(remote_config_key, {}).update(lj_self + lj_remote_config)

        load_once(self)
        self.readonly()
        return self

    def redis_instance(self, threshold):
        sharding_threshold = self.redis.get('sharding_threshold')
        return self.redis_instances[int(threshold) / int(sharding_threshold)]

    def push_payload(self, app_id, key, language='en'):
        payloads = self.get('main', {}).get('push', {}).\
            get('payloads', {}).get(app_id)
        payloads = payloads.get() if payloads else {}
        payload = payloads.get(key, {})
        alert = payload.get(language) or payload.get('en')
        args = payload.get('args', [])
        return alert, args

    def push_contents(self, app_id):
        contents = self.get('main', {}).get('push', {}).\
            get('push_contents', {}).get(app_id)
        contents = contents.get() if contents else {}
        return contents

    def signature_config(self, app_id):
        data_signature = self.get('main', {}).get('data_signature')
        re_1 = data_signature['remote_sig_factors'].get()[app_id]
        re_2 = data_signature['sig_keys'][app_id]
        return re_1, re_2

    def get_request_config(self, app_id=None):
        if app_id is not None:
            app_id = int(app_id) if isinstance(app_id, str) else app_id
            request_config = self.get('main', {}).\
                get('app', {}).get(app_id, {})
        else:
            request_config = self.get('main', {}).get('request', {})
        return request_config

    @staticmethod
    def register_preprocessor(resource_name, preprocessor):
        # TO-DO: give a hint if provided node_name does not exist.
        for resource in AutoloadResource.autoload_resources.values():
            if resource.name != resource_name:
                continue
            resource.register_preprocessor(preprocessor)

    @staticmethod
    def _create_config_from_template(config_file):
        if not os.path.exists(config_file):
            name, ext = os.path.splitext(config_file)
            templ_file = '%s.template%s' % (name, ext)
            if os.path.exists(templ_file):
                shutil.copyfile(templ_file, config_file)
            else:
                raise RuntimeError('no config.yaml or config.tempalte.yaml!')

    @property
    def remote_list(self):
        remote = []
        for k, v in self.items():
            if "remote_setting" in v:
                remote.append(k)
        return remote

    @property
    def ssm(self):
        return self.get('main', {}).get("ssm", {})

    @property
    def ssm_aws_id(self):
        return self.ssm.get('aws_access_key_id', '')

    @property
    def ssm_aws_key(self):
        return self.ssm.get('aws_secret_access_key', '')

    @property
    def apps(self):
        return self.get('main', {}).get('app', {})

    @property
    def appname(self):
        return self.get('main', {}).get('appname', 'noname')

    @property
    def request_slow_timeout(self):
        return self.get('main', {}).\
            get('request', {}).get('slow_timeout', 12000)

    @property
    def redynadb(self):
        return self.get('main', {}).get('redynadb', {})

    @property
    def redynadb_table_prefix(self):
        return self.redynadb.get('table_prefix', 'testapp')

    @property
    def redynadb_dynamo_configs(self):
        configs = {}
        dynamo_config = self.redynadb.get('dynamodb')
        if dynamo_config:
            configs[None] = dynamo_config
        return configs

    @property
    def redynadb_dblog(self):
        return self.redynadb.get('dblog', False)

    @property
    def redynadb_redis_configs(self):
        configs = {}
        redis_config = self.redynadb.get('redis_instances', {})
        configs[None] = redis_config
        return configs

    @property
    def redynadb_cache_enabled(self):
        return self.redynadb.get('cache_enabled', True)

    @property
    def redynadb_use_cluster_cache(self):
        return self.redynadb.get('use_cluster_cache', False)

    @property
    def redynadb_max_connections(self):
        return self.redynadb.get('max_connections', 100)

    @property
    def num_proxies(self):
        return int(self.get('main', {}).get('num_proxies', 1))

    @property
    def log(self):
        conf = self.get('main', {}).get('log', {})
        conf.setdefault('stdout', False)
        conf.setdefault('level', 'info')
        conf.setdefault('facility', 1)
        conf.setdefault('server', ["127.0.0.1", 514])
        conf.setdefault('filters', {})
        filters = conf.get('filters')
        for k, v in filters.items():
            if not v:
                filters[k] = 'OFF'
        return conf

    @property
    def statsd(self):
        conf = self.get('main', {}).get('statsd', {})
        conf.setdefault('server', ["127.0.0.1", 8125])
        return conf

    @property
    def push(self):
        return self.get('main', {}).get('push', {})

    @property
    def session_store(self):
        return self.get('main', {}).get('session_store', {})

    @property
    def data_store(self):
        return self.get('main', {}).get('data_store', {})

    @property
    def push_url(self):
        return self.get('main', {}).get('push', {}).get('url')

    @property
    def sqldb(self):
        return self.get('main', {}).get('sqldb', {})

    @property
    def pubsub(self):
        return self.get('main', {}).get('pubsub', {})

    @property
    def keepserver(self):
        return self.get('main', {}).get('push', {}).get('keepserver')

    @property
    def keepclient(self):
        url = self.keepserver
        if not url:
            return None
        from urllib.parse import urlparse
        # import urlparse
        from rock_keepserver.client import KeepClient
        p = urlparse.urlparse(url)
        return KeepClient(p.netloc.split(':')[0], p.netloc.split(':')[1], 2)

    @property
    def sentry_dsn(self):
        return self.get('main', {}).get('log', {}).get('sentry_dsn', '')

    @property
    def s3(self):
        return self.get('main', {}).get('s3', {})

    @property
    def remote_resource(self):
        return self.get('main', {}).get('remote_resource', {})

    @property
    def redis(self):
        return self.get('main', {}).get('redis', {})

    @property
    def redis_key_prefix(self):
        return self.redis.get('key_prefix') or self.appname

    @property
    def redis_instances(self):
        if not getattr(self, '_redis_instances', None):
            self._redis_instances = []
            for url in self.redis.get('instances', []):
                self._redis_instances.append(RedisStore.create(url))
        return self._redis_instances

    @property
    def sqs(self):
        return self.get('main', {}).get('sqs', {})
