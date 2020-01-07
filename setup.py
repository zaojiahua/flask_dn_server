from setuptools import setup, find_packages

install_requires = [
    'PyYAML==4.2b4',
    'flask==1.0.2',
    'gevent==1.4.0',
    'redis-py-cluster==1.3.6',
    'redis==2.10.6',
    'simplejson==3.16.0',
    'sqlalchemy==1.3.3',
    'pymysql==0.9.3'
]

setup(
    name='flask_dn_server',
    version='0.1',
    author='Gao Huang',
    author_email='2933682586@qq.com',
    url='https://github.com/zaojiahua/flask_dn_server',
    description='flask dn server',
    packages=find_packages(),
    zip_safe=False,
    install_requires=install_requires,)
