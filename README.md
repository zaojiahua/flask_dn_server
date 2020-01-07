# 大脑后端框架

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

## 使用示例

1. 需要对外提供服务的类，该类需要继承DNView。
2. 私有的方法，也就是以\_或者\_\_开头的类方法不会作为对外可以访问的服务。
3. 类方法名即为对外提供服务的url，类方法名中的下划线，转换为url中的路径。例如类方法名为update_info_name，则对外的服务url则为/update/info/name。
4. 请求数据默认转化为json类型的数据格式，在类方法中，通过self.\_request_data即可获取请求数据。
5. 返回的数据如果是可以转换成json格式的，自动转换为json格式，不能自动转换的，返回原始数据。
6. 跨域已经在框架内部解决。

```python
# 引入相关的模块
from dn.app import DNView


# 需要对外提供服务的话必须继承DNView
class Bar(DNView):
    # 方法名不能以_或者__开头，对外提供的url为/get/info，GET和POST方法都支持
    def get_info(self):
        print('**********打印请求数据**************')
        print(self._request_data)
        print(self._request_data['nickname'])
        print(self._request_data['age'])
        # 返回的数据如果是可以转换成json的，自动转换为json，不能自动转换的，返回原始数据
        return 'ok'

    # 对外提供的url为/update/info/name，GET和POST方法都支持
    def update_info_name(self):
        # 返回一个可以转化为json的对象
        # return dict(code=0, data='ok')
        return ['1', '2', '3']

    # 私有的方法不会作为view_functioin
    def __update_name(self):
        pass

    # 私有的方法不会作为view_functioin
    def _update_age(self):
        pass


# 没有继承DNView的不会对外提供服务
class Bing():
    pass
```

在自己的项目下，创建一个server.py文件，加入以下代码。

```python
from dn.app import DNApp
# 调用register_view_func之前，引入需要对外提供接口的模块，template.view模块就是上面的示例代码文件。
from template.view import home


app = DNApp.register_view_func()
```

返回的app就是flask的app对象，启动的时候按照正常启动flask的方法启动服务即可，一般输入的命令是flask run。