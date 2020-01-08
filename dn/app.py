import os
import sys
import time
import traceback
from urllib.parse import urlparse

from flask import Blueprint, Flask, g, json, jsonify, request, Response

from dn.common import log, sqldb
from dn.common.app import DNEnv
from dn.common.exceptions import AppBaseException, RequestDataException
# from dn.common.globals import config

from werkzeug.exceptions import HTTPException

logger = log.get_logger()


class AppIsNotMountableException(Exception):
    pass


class DNResponse(Response):
    @classmethod
    def force_type(cls, response, environ=None):
        if isinstance(response, (list, dict)):
            response = jsonify(response)
        return super(Response, cls).force_type(response, environ)


class DNFlask(Flask):
    def make_response(self, response):
        if isinstance(response, (list, dict)):
            response = jsonify(response)
        return super().make_response(response)


class DNView(object):

    @property
    def _request_data(self):
        try:
            jsondata = request.get_json() or request.values
        except Exception:
            jsondata = request.values
        return jsondata


class DNApp(DNEnv):
    def __init__(self, name_or_app, config_file="config.yaml"):
        if isinstance(name_or_app, Flask):
            import_name = name_or_app.import_name
            self.app = name_or_app
        else:
            import_name = name_or_app
            self.app = DNFlask(name_or_app)

        # 加入自己的Response
        self.app.response_class = DNResponse

        if os.path.isabs(config_file):
            self.config_file = config_file
        else:
            self.config_file = os.path.join(self.app.root_path, config_file)
        super(DNApp, self).__init__(import_name, config_file=self.config_file)
        self.app.add_url_rule("/health_check", view_func=self._health_check)

    def _health_check(self):
        return "DN works!"

    @property
    def flaskapp(self):
        return self.app

    @classmethod
    def init(cls):
        app = cls('')
        app.init_app()
        return app

    @classmethod
    def register_view_func(app_cls):
        app = app_cls.init()
        for cls in [cls for cls in DNView.__subclasses__()]:
            obj = cls()
            public_props = (name for name in dir(obj) if not name.startswith('_'))
            print(' * Public Rules as Belows:')
            for props in public_props:
                if hasattr(getattr(obj, props), '__call__'):
                    rule_name = '/' + props.replace('_', '/')
                    print(rule_name)
                    app.flaskapp.add_url_rule(rule_name, view_func=getattr(obj, props), methods=['GET', 'POST'])

        return app

    def init_app(self):
        # self.app.config.update(config)
        self.app.log = logger
        self.log = log.get_logger('api')
        self.app.before_request(self.before_request)
        self.app.after_request(self.after_request)
        self.app.teardown_request(self.teardown_request)
        self.init_error_handler()

    def init_error_handler(self):
        self.app.register_error_handler(Exception, self.error_handler)

        for code in [400, 401, 403, 404, 405, 406,
                     408, 409, 410, 411, 412, 413, 414,
                     415, 416, 417, 418, 422, 428, 429,
                     431, 500, 501, 502, 503, 504, 505]:
            self.app.register_error_handler(code, self.error_handler)

    def get_appid_from_urlpath(self):
        return g.app_prefix[3:] \
            if getattr(g, 'app_prefix', None) \
            else request.values.get('app_id', None)

    def get_urlprefix(self):
        path = '%s%s' % (request.script_root, request.path)
        return path.strip('/').split('/')[0]

    def before_request(self):
        logger.debug('REQUEST',
                     ('url', request.base_url),
                     ('endpoint', request.endpoint))
        g.rawdata = request.get_data(cache=True, parse_form_data=False)
        g.jsondata = {}
        if request.endpoint is None:
            return
        g.request_started = time.time()
        g.statsd_key = request.endpoint

        self.log.debug('REQUEST',
                       ('values', json.dumps(request.values.to_dict())))

        content = request.values.get('content')

        if content:
            try:
                g.jsondata = json.loads(content)
            except Exception:
                pass
        self.log.debug('REQUEST', 'jsondata: %s' % (g.jsondata))

    def teardown_request(self, exc):
        self.log.debug('teardown_request', exc)
        if exc:
            self.log.error('SHOULD_NOT_HAPPEN',
                           'teardown_request, has exception:%s' % exc)

        sqldb.clear_dbsession()

    def after_request(self, response):
        self.log.debug('after_request', response)
        if request.endpoint is None or response is None:
            return response

        code = -1

        """
        为了解决跨域的问题，添加以下的头部返回给客户端
        """
        header = response.headers
        # 要发送cookie，这里就不能设置为*，必须明确指定 http://www.xiaoyaoji.cn 不包含最后的/ request.referrer[:-1]
        if request.referrer is not None:
            matches = urlparse(request.referrer)
            header['Access-Control-Allow-Origin'] = matches.scheme + '://' + matches.netloc
        else:
            header['Access-Control-Allow-Origin'] = '*'
        # 同意将cookie发送到服务器
        header['Access-Control-Allow-Credentials'] = 'true'
        header['Access-Control-Allow-Headers'] = 'Authorization, content-type'
        header['Access-Control-Allow-Methods'] = 'GET, POST, DELETE'

        # if getattr(g, 'request_started', None) is not None:
        #     # t = (time.time() - g.request_started) * 1000
        #     if getattr(g, 'response_code', None) is None:
        #         code = response.status_code
        #     else:
        #         code = g.response_code
        #     if code // 100 == 2:
        #         if t > config.request_slow_timeout:
        #             request_data = getattr(g, 'jsondata', None)
        #             self.log.error('SLOWREQUEST',
        #                            'slow request of %s%s'
        #                            % (request.script_root, request.path),
        #                            {'request_url': request.url,
        #                             'request_data': request_data,
        #                             'request_cost': t})
        self.log_request(response, code)
        return response

    def error_handler(self, error):
        self.log.debug('error_handler', error)

        request_data = getattr(g, 'jsondata', None)
        if not isinstance(error, AppBaseException) \
                and not isinstance(error, RequestDataException):
            self.log.captureException(
                request_url=request.url, request_data=request_data)

        self.log.error('EXCEPTION', 'response_error', sys.exc_info()[1],
                       getattr(error, "description", ""))
        self.log.error('TRACEBACK', traceback.format_exc())

        return self.response_error(error)

    def response_error(self, error):
        if isinstance(error, HTTPException):
            g.response_code = error.code
            meta = {'code': error.code,
                    'error_type': error.__class__.__name__,
                    'error_message': error.description}
            if getattr(error, 'extra_info', None):
                meta.update(error.extra_info)
            if error.response and isinstance(error.response, dict):
                return jsonify(meta=meta, data=error.response)
            else:
                return jsonify(meta=meta)
        else:
            g.response_code = 500
            return jsonify(meta={'code': 500, 'error_type':
                                 error.__class__.__name__,
                                 'error_message': str(error)})

    def log_request(self, response, code=200):
        self.log.info('request',
                      request.remote_addr,
                      request.method,
                      request.script_root + request.path,
                      request.headers.get('Content-Length', '0'),
                      response.status_code,
                      code,
                      str(response.headers.get('Content-Length', '0')))

    def mount(self, block, mapping={}, skiplist=[]):
        block_name = block.__class__.__name__
        if block_name == 'module':
            block_name = block.__name__
        logger.info('MOUNT_BLOCK', block_name)
        initfunc = getattr(block, 'init', None)
        if initfunc is None or not callable(initfunc):
            raise Exception('%s does not have callable init func' % (block))
        blueprints = initfunc(self.app)
        toskips = set(skiplist)
        for bp in blueprints:
            if bp.name in mapping:
                url_prefix = '%s%s' % (mapping[bp.name], bp.url_prefix or '')
            else:
                url_prefix = bp.url_prefix

            logger.info('MOUNT_BLUEPRINT',
                        ('name', bp.name),
                        ('url_prefix', url_prefix),
                        ('skip', bp.name in toskips))
            if bp.name in toskips:
                continue
            self._mount(bp, url_prefix)

    def _mount(self, obj, url_prefix):
        if isinstance(obj, Blueprint):
            self.app.register_blueprint(obj, url_prefix=url_prefix)
        else:
            raise AppIsNotMountableException(
                '%s is not mountable, must be Blueproint' % obj)

    def run(self, host="0.0.0.0", port=5000):
        """
        dn Application Server.
        """
        from werkzeug.serving import run_simple

        options = {}
        options.setdefault('use_reloader', True)
        options.setdefault('use_debugger', True)
        run_simple(host,
                   port,
                   self.flaskapp,
                   **options)
