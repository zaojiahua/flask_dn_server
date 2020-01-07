import os
import pkgutil
import sys

from dn.common import log
from dn.common import sqldb
from dn.common.globals import config, config_object
from dn.common.yamlconfig import YamlConfig


class DNEnv(object):
    def __init__(self, import_name, config_file="config.yaml"):
        self.root_path = self.get_root_path(import_name)
        if os.path.isabs(config_file):
            self.config_file = config_file
        else:
            self.config_file = os.path.join(self.root_path, config_file)
        config_object.set_target_object(YamlConfig(self.config_file).preload())
        self.init_log()
        self.init_sqldb()
        self.init_app()

    def get_root_path(self, import_name):
        """Returns the path to a package or cwd if that cannot be found.  This
        returns the path of a package or the folder that contains a module.
        """
        if not import_name:
            return os.getcwd()
        # Module already imported and has a file attribute.  Use that first.
        mod = sys.modules.get(import_name)
        if mod is not None and hasattr(mod, '__file__'):
            return os.path.dirname(os.path.abspath(mod.__file__))

        # Next attempt: check the loader.
        loader = pkgutil.get_loader(import_name)

        # Loader does not exist or we're referring to an unloaded main module
        # or a main module without path (interactive sessions), go with the
        # current working directory.
        if loader is None or import_name == '__main__':
            return os.getcwd()

        filepath = loader.get_filename(import_name)

        return os.path.dirname(os.path.abspath(filepath))

    def init_log(self):
        log_config = config.log
        name = config.appname
        stdout = log_config['stdout']
        facility = log_config['facility']
        level = log_config['level'].upper()
        address = log_config['server']
        filters = log_config['filters']
        filters = dict(map(lambda x: ('.%s' % (x[0]), x[1]), filters.items()))

        log.setup(root=name, stdout=stdout, filters=filters)

        log.syslog_handlers(
            [name, 'werkzeug'], address=address,
            facility=facility, level=level)
        log.syslog_handlers(
            '%s.api' % name, address=address,
            facility=facility, level=level)

    def init_sqldb(self):
        conf = config.sqldb
        if not conf:
            return
        for name in conf:
            sqldb.get_dbsession(name)

    def init_app(self):
        pass


AppEnv = DNEnv


def init_DNEnv(import_name='', config_file="config.yaml"):
    env = DNEnv(import_name, config_file=config_file)
    return env
