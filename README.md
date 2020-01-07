# 大脑后端常用功能封装库

## Prerequisites

请使用 python3.6.x 和 python3.7.x 这两个Python版本。

## Installation

下载代码

```
git clone git@source.enncloud.cn:gaohuang/flask_dn_server.git
```

安装

```
cd flask_dn_server
python setup.py install
```

## 跨域

如下是一段完整的Flask代码。接下来就要在这段代码的基础上实现跨域功能。

```python
from flask import Flask

app = Flask(__name__)


@app.route('/a', methods=['GET', 'POST'])
def test_a():
    return "THIS IS TEST A!"


@app.route('/b', methods=['GET', 'POST'])
def test_b():
    return "THIS IS TEST B!"
```

首先引入相关的模块。

```python
from flask_dn import cross_origin, CORS
```

用法一、 针对单独的某个路由实现跨域，其他路由不跨域，比如说只针对/a请求实现跨域，/b请求不跨域。

```python
@app.route('/a', methods=['GET', 'POST'])
@cross_origin
def test_a():
    return "THIS IS TEST A!"
```

用法二、 全局设置，所有路由都跨域，也就是说/a请求跨域，/b请求也跨域，包括之后添加的所有请求都跨域。

```python
# app参数是flask的对象
CORS(app)
```