from setuptools import setup, find_packages

install_requires = [
    'flask==2.3.2',
    'gevent==1.4.0',
    'gunicorn',
]

setup(
    name='flask_dn_server',
    version='0.1.1',
    author='Gao Huang',
    author_email='2933682586@qq.com',
    url='https://github.com/zaojiahua/flask_dn_server',
    description='flask dn server',
    packages=find_packages(),
    zip_safe=False,
    install_requires=install_requires,)
