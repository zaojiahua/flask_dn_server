# -*- coding: utf-8 -*-
import functools
from urllib.parse import urlparse
from flask import request, make_response


def set_cors_headers(response):
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

    return response


def cross_origin(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        response = make_response(func(*args, **kwargs))
        return set_cors_headers(response)
    return wrapper


def CORS(app):

    @app.after_request
    def after_request(response):
        return set_cors_headers(response)
